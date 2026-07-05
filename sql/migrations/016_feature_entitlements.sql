-- À-la-carte feature entitlements per client.
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS bundle TEXT NOT NULL DEFAULT '';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS features JSONB NOT NULL DEFAULT '[]';

-- Existing clients keep everything working: grant the Business bundle so no
-- currently-configured site loses a capability when gating turns on.
UPDATE tenants SET bundle = 'business' WHERE bundle = '';
