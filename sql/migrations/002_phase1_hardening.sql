-- Phase 1: production hardening.
-- Per-tenant API keys, incremental crawl state, per-site CORS, crawl reports.

-- Tenant-scoped admin keys. The key itself is never stored, only a sha256 hash.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS api_key_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_api_key_hash ON tenants(api_key_hash);

-- Per-URL crawl state for incremental refresh. A page is re-embedded only when
-- its content hash changes; pages that disappear are pruned.
CREATE TABLE IF NOT EXISTS pages (
    id            BIGSERIAL PRIMARY KEY,
    site_id       BIGINT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL,
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_indexed  TIMESTAMPTZ,
    UNIQUE (site_id, url)
);
CREATE INDEX IF NOT EXISTS idx_pages_site ON pages(site_id);

-- Lock the widget to the customer's own domains. Comma separated origins;
-- empty means any origin (development).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS allowed_origins TEXT NOT NULL DEFAULT '';

-- Scheduled re-crawl interval in hours. 0 disables scheduling.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS recrawl_hours INT NOT NULL DEFAULT 0;

-- Machine-readable report of the last crawl (failed URLs, counts, timing).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_crawl_report JSONB NOT NULL DEFAULT '{}';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_indexed_at TIMESTAMPTZ;
