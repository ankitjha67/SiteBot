-- Batch B: messaging channels, follow-up suggestions, widget language,
-- team member keys, weekly digests.

-- Channel credentials, per site. Tokens are stored server-side only and are
-- never exposed through the widget config endpoint.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS telegram_bot_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS slack_bot_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS slack_signing_secret TEXT NOT NULL DEFAULT '';

-- Follow-up question suggestions after each answered message.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS followups_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- Widget UI language (button labels, placeholders - answers already follow
-- the visitor's language).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS widget_language TEXT NOT NULL DEFAULT 'en';

-- Weekly analytics digest delivered to a webhook (Slack/Zapier/anything).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS digest_webhook_url TEXT NOT NULL DEFAULT '';

-- Team member keys: extra API keys per tenant with a role. The tenant's
-- original key (tenants.api_key_hash) acts as the owner/admin key.
CREATE TABLE IF NOT EXISTS tenant_keys (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    role         TEXT NOT NULL DEFAULT 'admin',   -- admin | viewer
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tenant_keys_tenant ON tenant_keys(tenant_id);
