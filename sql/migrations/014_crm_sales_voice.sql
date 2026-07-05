-- CRM connectors, lead qualification/booking, and phone-voice support.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS crm_provider TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS crm_api_key TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS booking_url TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS qualifying_questions JSONB NOT NULL DEFAULT '[]';

-- Qualification data + score captured with each lead.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS qualification JSONB NOT NULL DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS score INT NOT NULL DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS crm_synced BOOLEAN NOT NULL DEFAULT FALSE;
