"""Payments ledger, audit trail, and gateway integrations (Razorpay + Stripe).

The ledger (`payments` table) is the single source of truth for money. Every
gateway webhook and every manual entry writes here, so the admin console can
show a complete, auditable history independent of any provider dashboard.

Razorpay is first-class for India (INR); Stripe covers cards globally. Both are
optional — without keys, order creation returns a clear 503 and the ledger
still works for manual/recorded entries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import httpx
from fastapi import HTTPException

from sitebot.config import Settings
from sitebot.db import get_pool

log = logging.getLogger(__name__)


# ------------------------------- audit trail -------------------------------
async def audit(
    actor: str, action: str, target_type: str = "", target_id: str = "",
    detail: dict | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO audit_log (actor, action, target_type, target_id, detail) "
        "VALUES ($1, $2, $3, $4, $5)",
        actor, action, target_type, str(target_id), json.dumps(detail or {}),
    )


# --------------------------------- ledger ----------------------------------
async def record_payment(
    tenant_id: int | None, provider: str, amount_cents: int, *,
    status: str = "paid", currency: str = "usd", description: str = "",
    provider_txn_id: str = "", provider_order_id: str = "", metadata: dict | None = None,
) -> int:
    """Write a payment to the ledger (idempotent on provider+txn_id) and audit
    it. Returns the ledger row id."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO payments (tenant_id, provider, provider_txn_id, provider_order_id, "
        "amount_cents, currency, status, description, metadata) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
        "ON CONFLICT (provider, provider_txn_id) WHERE provider_txn_id <> '' "
        "DO UPDATE SET status = EXCLUDED.status, updated_at = now() "
        "RETURNING id",
        tenant_id, provider, provider_txn_id, provider_order_id,
        amount_cents, currency, status, description, json.dumps(metadata or {}),
    )
    await audit(
        f"provider:{provider}", f"payment.{status}", "payment", str(row["id"]),
        {"amount_cents": amount_cents, "currency": currency, "tenant_id": tenant_id},
    )
    return int(row["id"])


# -------------------------------- razorpay ---------------------------------
def _razorpay_auth(settings: Settings) -> tuple[str, str]:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured.")
    return settings.razorpay_key_id, settings.razorpay_key_secret


async def create_razorpay_order(
    tenant_id: int, amount_cents: int, settings: Settings, currency: str = "INR"
) -> dict:
    """Create a Razorpay order. Returns {order_id, amount, currency, key_id} for
    the checkout widget. Records a 'created' ledger entry."""
    key_id, key_secret = _razorpay_auth(settings)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json={
                "amount": amount_cents, "currency": currency,
                "notes": {"tenant_id": str(tenant_id)},
            },
        )
    if resp.status_code not in (200, 201):
        log.warning("razorpay order failed: %s %s", resp.status_code, resp.text[:200])
        raise HTTPException(status_code=502, detail="Could not create the Razorpay order.")
    order = resp.json()
    await record_payment(
        tenant_id, "razorpay", amount_cents, status="created", currency=currency,
        provider_order_id=order["id"], description="Razorpay order created",
    )
    return {
        "order_id": order["id"], "amount": amount_cents,
        "currency": currency, "key_id": key_id,
    }


def verify_razorpay_signature(
    order_id: str, payment_id: str, signature: str, secret: str
) -> bool:
    """Checkout callback signature = HMAC-SHA256(order_id|payment_id) hex."""
    if not secret:
        return False
    expected = hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_razorpay_webhook(body: bytes, signature: str, secret: str) -> bool:
    """Webhook signature = HMAC-SHA256(raw body) hex."""
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


async def handle_razorpay_webhook(body: bytes, signature: str, settings: Settings) -> dict:
    """Verify and record a Razorpay webhook (payment.captured / .failed)."""
    if not verify_razorpay_webhook(body, signature, settings.razorpay_webhook_secret):
        raise HTTPException(status_code=403, detail="Bad Razorpay signature.")
    event = json.loads(body or b"{}")
    kind = event.get("event", "")
    pay = (event.get("payload", {}).get("payment", {}) or {}).get("entity", {})
    if not pay:
        return {"ok": True, "ignored": kind}
    tenant_id = None
    try:
        tenant_id = int(pay.get("notes", {}).get("tenant_id"))
    except (TypeError, ValueError):
        tenant_id = None
    status = "paid" if kind == "payment.captured" else (
        "failed" if kind == "payment.failed" else "created"
    )
    await record_payment(
        tenant_id, "razorpay", int(pay.get("amount", 0)), status=status,
        currency=pay.get("currency", "INR"), provider_txn_id=pay.get("id", ""),
        provider_order_id=pay.get("order_id", ""), description=f"Razorpay {kind}",
        metadata={"method": pay.get("method"), "email": pay.get("email")},
    )
    return {"ok": True, "recorded": kind}


# --------------------------------- stripe ----------------------------------
async def handle_stripe_payment_event(event: dict) -> None:
    """Record a Stripe payment event (invoice.paid / payment_intent.*) into the
    ledger. Called from billing.handle_webhook after signature verification."""
    kind = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if kind not in ("invoice.paid", "invoice.payment_failed",
                    "payment_intent.succeeded", "charge.refunded"):
        return
    amount = int(obj.get("amount_paid") or obj.get("amount") or obj.get("amount_received") or 0)
    status = {
        "invoice.paid": "paid", "payment_intent.succeeded": "paid",
        "invoice.payment_failed": "failed", "charge.refunded": "refunded",
    }.get(kind, "created")
    cust = obj.get("customer")
    tenant_id = None
    if cust:
        pool = await get_pool()
        tenant_id = await pool.fetchval(
            "SELECT id FROM tenants WHERE stripe_customer_id = $1", cust
        )
    await record_payment(
        int(tenant_id) if tenant_id else None, "stripe", amount, status=status,
        currency=obj.get("currency", "usd"), provider_txn_id=obj.get("id", ""),
        description=f"Stripe {kind}",
    )
