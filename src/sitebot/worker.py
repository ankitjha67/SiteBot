"""Background worker (arq on Redis): ingestion jobs and scheduled re-crawls.

Run with:  arq sitebot.worker.WorkerSettings
The API enqueues jobs by name when REDIS_URL is set; otherwise it falls back
to FastAPI BackgroundTasks (dev mode, single process). Only the arq CLI
imports this module, so worker-only imports live here.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from sitebot import store
from sitebot.config import get_settings
from sitebot.db import apply_schema, close_pool, get_pool
from sitebot.ingest import ingest_site

log = logging.getLogger(__name__)


async def ingest_site_task(
    ctx: dict[str, Any], site_id: int, start_url: str, full: bool = False
) -> dict[str, int]:
    """Crawl and (re)index one site. Errors are recorded on the site row."""
    settings = get_settings()
    try:
        pages, chunks = await ingest_site(site_id, start_url, settings, full=full)
        return {"pages": pages, "chunks": chunks}
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest failed for site %s", site_id)
        await store.set_site_status(site_id, "error", str(exc)[:500])
        return {"pages": 0, "chunks": 0}


async def recrawl_due_sites(ctx: dict[str, Any]) -> int:
    """Cron: enqueue a re-crawl for every site whose refresh interval elapsed."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, start_url FROM sites "
        "WHERE recrawl_hours > 0 AND status = 'ready' "
        "AND (last_indexed_at IS NULL "
        "     OR last_indexed_at < now() - (recrawl_hours || ' hours')::interval)"
    )
    redis = ctx["redis"]
    for row in rows:
        await redis.enqueue_job("ingest_site_task", int(row["id"]), row["start_url"])
    if rows:
        log.info("scheduled re-crawl for %d site(s)", len(rows))
    return len(rows)


async def purge_retention(ctx: dict[str, Any]) -> int:
    """Cron: delete conversations older than each site's retention window."""
    deleted = await store.purge_expired_conversations()
    if deleted:
        log.info("retention purge removed %d conversation(s)", deleted)
    return deleted


async def send_weekly_digests(ctx: dict[str, Any]) -> int:
    """Cron: send a 7-day analytics summary to each site's digest target
    (Slack/Zapier webhook or email)."""
    from sitebot import analytics, email_out, webhooks

    settings = get_settings()
    sent = 0
    for site in await store.sites_with_digest():
        try:
            summary = await analytics.site_summary(int(site["id"]), days=7)
            summary["site"] = site["slug"]
            if site["digest_channel"] == "email" and settings.smtp_configured:
                subject, text = email_out.digest_email(site["slug"], summary)
                ok = await email_out.send_email(settings, site["notify_email"], subject, text)
            else:
                ok = await webhooks.deliver(
                    site["digest_webhook_url"], "digest.weekly", summary
                )
            sent += 1 if ok else 0
        except Exception:  # noqa: BLE001 - one bad target must not stop the rest
            log.exception("weekly digest failed for site %s", site["slug"])
    if sent:
        log.info("sent %d weekly digest(s)", sent)
    return sent


async def _startup(ctx: dict[str, Any]) -> None:
    from sitebot.logging_setup import setup_logging

    setup_logging(get_settings())
    await apply_schema()


async def _shutdown(ctx: dict[str, Any]) -> None:
    await close_pool()


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL must be set to run the worker.")
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    """arq entrypoint: arq sitebot.worker.WorkerSettings"""

    functions = [ingest_site_task, recrawl_due_sites, purge_retention, send_weekly_digests]
    cron_jobs = [
        cron(recrawl_due_sites, minute={0, 30}),  # check twice an hour
        cron(purge_retention, hour={3}, minute={10}),  # nightly GDPR purge
        cron(send_weekly_digests, weekday={0}, hour={8}, minute={0}),  # Monday 08:00 UTC
    ]
    on_startup = _startup
    on_shutdown = _shutdown
    job_timeout = 3600  # big sites take a while
    max_jobs = 4


# arq reads WorkerSettings.redis_settings as a plain attribute at startup.
# When imported without REDIS_URL (e.g. tests) the worker cannot run anyway,
# and arq falls back to its default localhost settings, which is acceptable.
with contextlib.suppress(RuntimeError):
    WorkerSettings.redis_settings = _redis_settings()
