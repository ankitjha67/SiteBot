-- Batch C: AI Actions and the WhatsApp channel.

-- Declarative per-site actions the model can invoke while answering:
--   http  - call an external API (order status, stock lookup, ...)
--   link  - hand the visitor a URL (booking page, signup, ...)
CREATE TABLE IF NOT EXISTS actions (
    id           BIGSERIAL PRIMARY KEY,
    site_id      BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT 'http',   -- http | link
    method       TEXT NOT NULL DEFAULT 'GET',    -- GET | POST
    url          TEXT NOT NULL DEFAULT '',       -- may contain {param} placeholders
    headers      JSONB NOT NULL DEFAULT '{}',    -- static headers (e.g. API keys)
    params       JSONB NOT NULL DEFAULT '[]',    -- [{name, description, required, location}]
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (site_id, name)
);
CREATE INDEX IF NOT EXISTS idx_actions_site ON actions(site_id);

-- WhatsApp Cloud API credentials, per site. Stored server-side only.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS whatsapp_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS whatsapp_phone_id TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS whatsapp_verify_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS whatsapp_app_secret TEXT NOT NULL DEFAULT '';
