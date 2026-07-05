-- Phase 3: scale and platform.
-- Billing state, white-label flag, answer cache for cost control.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_status TEXT NOT NULL DEFAULT 'none';

-- White label: hide the "Powered by SiteBot" footer (paid plans).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS hide_branding BOOLEAN NOT NULL DEFAULT FALSE;

-- Exact-question answer cache. Serving a repeated question from here costs
-- nothing and returns instantly. Rows expire by created_at + TTL at read time.
CREATE TABLE IF NOT EXISTS answer_cache (
    id             BIGSERIAL PRIMARY KEY,
    site_id        BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    question_hash  TEXT NOT NULL,
    answer         TEXT NOT NULL,
    sources        JSONB NOT NULL DEFAULT '[]',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (site_id, question_hash)
);
