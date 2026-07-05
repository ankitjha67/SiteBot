"""Native CRM connectors: captured leads land in the client's CRM
automatically - no Zapier hop required.

Supported per-site providers (crm_provider + crm_api_key, encrypted at rest):
    hubspot    Private-app token. Creates/updates a Contact by email.
    pipedrive  API token. Creates a Person + a Lead attached to it.
    webhook    Generic JSON POST (crm_api_key unused) - covers everything else.

Sync is best-effort in a background task: a CRM outage must never block the
visitor's lead submission. Success flips leads.crm_synced for the dashboard.
"""

from __future__ import annotations

import logging

import httpx

from sitebot.actions import is_safe_url
from sitebot.db import get_pool

log = logging.getLogger(__name__)

_TIMEOUT = 15.0


async def _hubspot(api_key: str, lead: dict) -> bool:
    """Upsert a HubSpot contact by email (private app token)."""
    props = {
        "email": lead["email"],
        "firstname": lead.get("name") or "",
        "hs_lead_status": "NEW",
        "message": (lead.get("note") or "")[:5000],
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"properties": props},
        )
        if resp.status_code == 409:  # exists: update instead
            contact_id = resp.json().get("message", "").rsplit("ID: ", 1)[-1]
            if contact_id.isdigit():
                resp = await client.patch(
                    f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"properties": props},
                )
        return resp.status_code in (200, 201)


async def _pipedrive(api_key: str, lead: dict) -> bool:
    """Create a Pipedrive person, then a lead attached to it."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.pipedrive.com/v1/persons",
            params={"api_token": api_key},
            json={"name": lead.get("name") or lead["email"], "email": [lead["email"]]},
        )
        if resp.status_code not in (200, 201):
            return False
        person_id = resp.json().get("data", {}).get("id")
        resp = await client.post(
            "https://api.pipedrive.com/v1/leads",
            params={"api_token": api_key},
            json={
                "title": f"SiteBot lead: {lead.get('name') or lead['email']}",
                "person_id": person_id,
            },
        )
        return resp.status_code in (200, 201)


async def _webhook(url: str, lead: dict) -> bool:
    if not is_safe_url(url):
        return False
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        resp = await client.post(url, json={"event": "lead.created", **lead})
        return 200 <= resp.status_code < 300


async def push_lead(
    lead_id: int, provider: str, api_key: str, webhook_url: str, lead: dict
) -> None:
    """Deliver one lead to the configured CRM; record the outcome."""
    ok = False
    try:
        if provider == "hubspot" and api_key:
            ok = await _hubspot(api_key, lead)
        elif provider == "pipedrive" and api_key:
            ok = await _pipedrive(api_key, lead)
        elif provider == "webhook" and webhook_url:
            ok = await _webhook(webhook_url, lead)
        else:
            return  # no CRM configured
    except Exception:  # noqa: BLE001 - CRM outages must not surface to visitors
        log.exception("CRM push failed (provider=%s lead=%s)", provider, lead_id)
        return
    if ok:
        pool = await get_pool()
        await pool.execute("UPDATE leads SET crm_synced = TRUE WHERE id = $1", lead_id)
    else:
        log.warning("CRM push rejected (provider=%s lead=%s)", provider, lead_id)
