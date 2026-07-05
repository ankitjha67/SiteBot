"""Feature catalog, bundles, and pricing for à-la-carte monetisation.

A client's plan is a bundle (pre-made set of features at a bundle price) plus
any à-la-carte features they add on top. What a client can do is decided by
their *effective* feature set = bundle features ∪ à-la-carte features.

Prices are monthly, in cents. This module is the single source of truth; the
dashboard and billing read from here so there's one place to change pricing.
"""

from __future__ import annotations

# code -> {name, price_cents, blurb}. Core website chat + basic lead capture
# are always included and are NOT listed here (never gated).
FEATURES: dict[str, dict] = {
    "channels": {
        "name": "Messaging Channels",
        "price_cents": 3900,
        "blurb": "WhatsApp, Slack, Telegram, Messenger, Teams, and SMS.",
    },
    "voice": {
        "name": "Phone Voice AI",
        "price_cents": 7900,
        "blurb": "Answer phone calls from the knowledge base via Twilio.",
    },
    "crm": {
        "name": "CRM Sync",
        "price_cents": 4900,
        "blurb": "Push qualified leads to HubSpot or Pipedrive automatically.",
    },
    "lead_qualification": {
        "name": "Lead Qualification & Booking",
        "price_cents": 2900,
        "blurb": "Qualifying questions, lead scoring, and 24/7 booking links.",
    },
    "ai_actions": {
        "name": "AI Actions",
        "price_cents": 2900,
        "blurb": "Let the bot call live APIs mid-answer (order status, bookings).",
    },
    "secrets_guardian": {
        "name": "Secrets Guardian",
        "price_cents": 5900,
        "blurb": "Never reveal confidential business data, even under a jailbreak.",
    },
    "analytics_pro": {
        "name": "Advanced Analytics & Reports",
        "price_cents": 1900,
        "blurb": "Deflection metrics, CSV exports, and weekly digests.",
    },
    "auto_branding": {
        "name": "Auto-Branding",
        "price_cents": 1900,
        "blurb": "Match the widget to the site's colour and font automatically.",
    },
}

# Base price for the core product (website chat + RAG + basic lead capture),
# charged when a client buys à-la-carte without a bundle.
BASE_PRICE_CENTS = 4900

# Pre-made bundles. price_cents is the all-in monthly price for the bundle.
BUNDLES: dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "price_cents": 4900,
        "features": [],  # core only
        "blurb": "Website chat that answers from your content, with lead capture.",
    },
    "growth": {
        "name": "Growth",
        "price_cents": 12900,
        "features": ["channels", "lead_qualification", "analytics_pro", "auto_branding"],
        "blurb": "Everything in Starter plus messaging channels, sales tools, and analytics.",
    },
    "business": {
        "name": "Business",
        "price_cents": 29900,
        "features": list(FEATURES.keys()),  # all features
        "blurb": "The full platform: every channel, voice, CRM, and security.",
    },
}

ALL_FEATURE_KEYS = frozenset(FEATURES)


def effective_features(bundle: str, alacarte: list[str]) -> frozenset[str]:
    """The complete set a client can use = bundle features + à-la-carte adds."""
    eff: set[str] = set(BUNDLES.get(bundle, {}).get("features", []))
    eff.update(k for k in (alacarte or []) if k in FEATURES)
    return frozenset(eff)


def monthly_cost_cents(bundle: str, alacarte: list[str]) -> int:
    """Monthly total: bundle price (or base) plus à-la-carte features that the
    bundle doesn't already include."""
    bundle_feats = set(BUNDLES.get(bundle, {}).get("features", []))
    extras = [k for k in (alacarte or []) if k in FEATURES and k not in bundle_feats]
    base = BUNDLES[bundle]["price_cents"] if bundle in BUNDLES else BASE_PRICE_CENTS
    return base + sum(FEATURES[k]["price_cents"] for k in extras)


def catalog() -> dict:
    """The full menu the dashboard renders: features + bundles, with prices."""
    return {
        "base_price_cents": BASE_PRICE_CENTS,
        "features": [
            {"key": k, **v} for k, v in FEATURES.items()
        ],
        "bundles": [
            {"key": k, **v} for k, v in BUNDLES.items()
        ],
    }
