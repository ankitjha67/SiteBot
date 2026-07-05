"""Outbound webhook delivery for leads and handoffs.

A webhook URL per site is the one integration that composes with everything:
Slack incoming webhooks, Zapier, Make, n8n, or the customer's own endpoint.
Delivery is fire-and-forget with retries; a failure never breaks the visitor
flow.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), reraise=True)
async def _post(url: str, payload: dict[str, Any]) -> None:
    # follow_redirects=False so a public URL cannot 30x-bounce the request to an
    # internal host after the set-time SSRF check (defense in depth).
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


async def deliver(url: str, event: str, payload: dict[str, Any]) -> bool:
    """Send {event, data} to the webhook. Returns True on success."""
    if not url:
        return False
    # Re-validate at send time: the URL was checked when saved, but guard again
    # in case it was set before this check existed.
    from sitebot.actions import is_safe_url

    if not is_safe_url(url):
        log.warning("webhook blocked by SSRF guard: %s", event)
        return False
    body = {"event": event, "data": payload}
    # Slack incoming webhooks require a "text" field; include a readable line
    # so the same URL works for Slack and generic receivers.
    body["text"] = _summary_line(event, payload)
    try:
        await _post(url, body)
        return True
    except Exception:  # noqa: BLE001
        log.exception("webhook delivery failed: %s", event)
        return False


def _summary_line(event: str, payload: dict[str, Any]) -> str:
    if event == "lead.created":
        return f"New lead: {payload.get('email', '?')} — {payload.get('note', '')}".strip()
    if event == "handoff.requested":
        return (
            f"Human handoff requested by {payload.get('email') or 'a visitor'}: "
            f"{payload.get('message', '')}"
        ).strip()
    return f"SiteBot event: {event}"
