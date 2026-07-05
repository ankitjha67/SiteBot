-- Payments ledger: the system of record for every charge, from any provider.
CREATE TABLE IF NOT EXISTS payments (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT REFERENCES tenants(id) ON DELETE SET NULL,
    provider      TEXT NOT NULL,                 -- stripe | razorpay | manual
    provider_txn_id TEXT NOT NULL DEFAULT '',     -- gateway transaction / payment id
    provider_order_id TEXT NOT NULL DEFAULT '',
    amount_cents  BIGINT NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'usd',
    status        TEXT NOT NULL DEFAULT 'created', -- created | paid | failed | refunded
    description   TEXT NOT NULL DEFAULT '',
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_payments_tenant ON payments (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_txn
    ON payments (provider, provider_txn_id) WHERE provider_txn_id <> '';

-- Audit trail: who did what, so an admin can reconstruct any change.
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor       TEXT NOT NULL,                    -- admin | tenant:<id> | system | provider
    action      TEXT NOT NULL,                    -- plan.change, feature.enable, payment.paid...
    target_type TEXT NOT NULL DEFAULT '',
    target_id   TEXT NOT NULL DEFAULT '',
    detail      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log (target_type, target_id);
