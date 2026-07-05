"""Stripe billing (Phase 3). Entirely optional: without STRIPE_SECRET_KEY the
endpoints return 503 and the rest of the product works unchanged.

Model: one subscription per tenant. The Stripe price id maps to a plan name
via STRIPE_PRICE_MAP_JSON; the webhook keeps tenants.plan in sync, and plan
quotas are enforced at request time by ratelimit.enforce_monthly_quota.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from sitebot.config import Settings
from sitebot.db import get_pool

log = logging.getLogger(__name__)


def _stripe(settings: Settings):  # type: ignore[no-untyped-def]
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    try:
        import stripe
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="Billing requires the stripe package: pip install stripe"
        ) from exc
    stripe.api_key = settings.stripe_secret_key
    return stripe


async def create_checkout_session(
    tenant_id: int, price_id: str, success_url: str, cancel_url: str, settings: Settings
) -> str:
    """Create a Stripe Checkout session for a subscription. Returns the URL."""
    stripe = _stripe(settings)
    pool = await get_pool()
    tenant = await pool.fetchrow(
        "SELECT id, name, email, stripe_customer_id FROM tenants WHERE id = $1", tenant_id
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    customer_id = tenant["stripe_customer_id"]
    if not customer_id:
        customer = stripe.Customer.create(
            name=tenant["name"], email=tenant["email"] or None, metadata={"tenant_id": tenant_id}
        )
        customer_id = customer.id
        await pool.execute(
            "UPDATE tenants SET stripe_customer_id = $2 WHERE id = $1", tenant_id, customer_id
        )

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"tenant_id": str(tenant_id)},
    )
    return str(session.url)


async def handle_webhook(payload: bytes, signature: str, settings: Settings) -> dict[str, str]:
    """Verify and process a Stripe webhook; keep tenant plan/status in sync."""
    stripe = _stripe(settings)
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET is not set.")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except Exception as exc:  # noqa: BLE001 - bad signature or payload
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from exc

    kind = event["type"]
    obj = event["data"]["object"]
    pool = await get_pool()

    if kind in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = obj["customer"]
        status = obj["status"]  # active | trialing | past_due | canceled | ...
        price_id = ""
        items = obj.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id", "")
        plan = settings.stripe_price_map.get(price_id, "")
        if plan and status in ("active", "trialing"):
            await pool.execute(
                "UPDATE tenants SET plan = $2, billing_status = $3, "
                "stripe_subscription_id = $4 WHERE stripe_customer_id = $1",
                customer_id, plan, status, obj["id"],
            )
        else:
            await pool.execute(
                "UPDATE tenants SET billing_status = $2 WHERE stripe_customer_id = $1",
                customer_id, status,
            )
        log.info("billing: subscription %s for customer %s -> %s", status, customer_id, plan)

    elif kind == "customer.subscription.deleted":
        customer_id = obj["customer"]
        await pool.execute(
            "UPDATE tenants SET plan = 'free', billing_status = 'canceled', "
            "stripe_subscription_id = NULL WHERE stripe_customer_id = $1",
            customer_id,
        )
        log.info("billing: subscription canceled for customer %s", customer_id)

    return {"received": kind}


async def usage_this_month(tenant_id: int) -> int:
    """Answered messages this calendar month; the metered-billing quantity."""
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "SELECT count(*) FROM usage_events WHERE tenant_id = $1 AND kind = 'message' "
            "AND created_at >= date_trunc('month', now())",
            tenant_id,
        )
        or 0
    )
