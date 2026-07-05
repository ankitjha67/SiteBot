-- Per-site JavaScript rendering toggle (Playwright) for SPA-heavy sites.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS render_js BOOLEAN NOT NULL DEFAULT FALSE;

-- Customer user accounts: email + password login for the dashboard,
-- scoped to a tenant. Session tokens are stored hashed, like API keys.
CREATE TABLE IF NOT EXISTS tenant_users (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email       TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'admin',      -- admin | viewer
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES tenant_users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON user_sessions (expires_at);
