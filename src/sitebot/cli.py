"""Command line interface. Handy for local setup, ops, and quick demos."""

from __future__ import annotations

import argparse
import asyncio
import secrets
from urllib.parse import urlparse

from sitebot.config import get_settings
from sitebot.db import apply_schema, close_pool, get_pool, run_migrations
from sitebot.ingest import ingest_site


async def _init_db() -> None:
    await apply_schema()
    print("Schema applied and migrations run.")
    await close_pool()


async def _migrate() -> None:
    await apply_schema()
    applied = await run_migrations()
    print(f"Applied {len(applied)} new migration(s): {applied or 'none pending'}")
    await close_pool()


async def _create_tenant(name: str, email: str, plan: str) -> None:
    from sitebot import store
    from sitebot.auth import generate_tenant_key

    await apply_schema()
    key, key_hash = generate_tenant_key()
    tenant_id = await store.create_tenant(name, email, plan, key_hash)
    print(f"Tenant id:  {tenant_id}")
    print(f"API key:    {key}")
    print("Store this key now; only its hash is kept.")
    await close_pool()


async def _ingest_url(url: str, name: str | None, full: bool) -> None:
    settings = get_settings()
    await apply_schema()
    slug = urlparse(url).netloc.replace(".", "-").lower()
    public_key = "pk_" + secrets.token_urlsafe(24)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        tenant_id = await conn.fetchval(
            "INSERT INTO tenants (name) VALUES ($1) RETURNING id", name or slug
        )
        site_id = await conn.fetchval(
            "INSERT INTO sites (tenant_id, slug, start_url, public_key) "
            "VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (slug) DO UPDATE SET start_url = EXCLUDED.start_url "
            "RETURNING id",
            tenant_id, slug, url, public_key,
        )
        row = await conn.fetchrow("SELECT public_key FROM sites WHERE id = $1", site_id)
    print(f"Crawling and indexing {url} ...")
    pages, chunks = await ingest_site(site_id, url, settings, full=full)
    print(f"Done. Pages: {pages}, Chunks written: {chunks}")
    print(f"Site slug:  {slug}")
    print(f"Public key: {row['public_key']}")
    print("Use the public key in widget/demo.html to test the chat.")
    await close_pool()


async def _recrawl(slug: str, full: bool) -> None:
    from sitebot import store

    settings = get_settings()
    site = await store.get_site_by_slug(slug)
    if site is None:
        print(f"No site with slug {slug}")
        return
    print(f"Re-crawling {site.start_url} ({'full' if full else 'incremental'}) ...")
    pages, chunks = await ingest_site(site.id, site.start_url, settings, full=full)
    print(f"Done. Pages: {pages}, Chunks written: {chunks}")
    await close_pool()


async def _eval(slug: str, file: str, answers: bool, threshold: float) -> int:
    from sitebot.evals import format_report, load_eval_set, pass_rate, run_eval

    settings = get_settings()
    cases = load_eval_set(file)
    results = await run_eval(slug, cases, settings, answers=answers)
    print(format_report(results, answers))
    await close_pool()
    if pass_rate(results) < threshold:
        print(f"FAIL: pass rate below threshold {threshold:.0%}")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="sitebot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create tables, indexes, and run migrations.")
    sub.add_parser("migrate", help="Run pending SQL migrations.")

    ten = sub.add_parser("create-tenant", help="Create a tenant and print its API key.")
    ten.add_argument("name")
    ten.add_argument("--email", default="")
    ten.add_argument("--plan", default="trial")

    ing = sub.add_parser("ingest-url", help="Create a site and index it in one step.")
    ing.add_argument("url", help="Start URL of the website to index.")
    ing.add_argument("--name", default=None, help="Tenant display name.")
    ing.add_argument("--full", action="store_true", help="Force re-embedding everything.")

    rec = sub.add_parser("recrawl", help="Re-crawl an existing site by slug.")
    rec.add_argument("slug")
    rec.add_argument("--full", action="store_true", help="Force re-embedding everything.")

    srv = sub.add_parser("serve", help="Run the API server.")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument(
        "--workers", type=int, default=1,
        help="Worker processes. Production rule of thumb: CPU cores. "
        "Each worker gets its own DB pool; keep workers * DB_POOL_MAX below "
        "Postgres max_connections.",
    )

    sub.add_parser("worker", help="Run the background worker (requires REDIS_URL).")

    ev = sub.add_parser(
        "eval", help="Run an answer-quality eval set against an indexed site."
    )
    ev.add_argument("slug", help="Site slug to evaluate.")
    ev.add_argument("file", help="JSON eval set (see src/sitebot/evals.py docstring).")
    ev.add_argument(
        "--answers", action="store_true",
        help="Also run the full LLM pipeline (costs model calls).",
    )
    ev.add_argument(
        "--threshold", type=float, default=0.8,
        help="Exit non-zero when pass rate falls below this (CI gate).",
    )

    args = parser.parse_args()

    if args.command == "init-db":
        asyncio.run(_init_db())
    elif args.command == "migrate":
        asyncio.run(_migrate())
    elif args.command == "create-tenant":
        asyncio.run(_create_tenant(args.name, args.email, args.plan))
    elif args.command == "ingest-url":
        asyncio.run(_ingest_url(args.url, args.name, args.full))
    elif args.command == "recrawl":
        asyncio.run(_recrawl(args.slug, args.full))
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "sitebot.app:app", host=args.host, port=args.port,
            workers=args.workers, reload=False,
        )
    elif args.command == "worker":
        from arq.worker import run_worker

        from sitebot.worker import WorkerSettings

        run_worker(WorkerSettings)  # type: ignore[arg-type]
    elif args.command == "eval":
        raise SystemExit(asyncio.run(_eval(args.slug, args.file, args.answers, args.threshold)))


if __name__ == "__main__":
    main()
