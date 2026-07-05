-- Roadmap fill: native email alerts, SMS (Twilio), Messenger, Microsoft Teams.
-- SMTP server config is platform-level (env); each site sets where alerts go
-- and its own channel credentials.

-- Owner alert address for leads/handoffs (in addition to webhooks).
ALTER TABLE sites ADD COLUMN IF NOT EXISTS notify_email TEXT NOT NULL DEFAULT '';

-- Twilio SMS channel.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS twilio_account_sid TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS twilio_auth_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS twilio_from TEXT NOT NULL DEFAULT '';

-- Facebook Messenger / Instagram (Meta) channel.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS messenger_page_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS messenger_verify_token TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS messenger_app_secret TEXT NOT NULL DEFAULT '';

-- Microsoft Teams (Bot Framework) channel.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS teams_app_id TEXT NOT NULL DEFAULT '';
ALTER TABLE sites ADD COLUMN IF NOT EXISTS teams_app_password TEXT NOT NULL DEFAULT '';

-- Digest delivery target: 'webhook' (default) or 'email'.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS digest_channel TEXT NOT NULL DEFAULT 'webhook';

-- Animated avatar persona for the widget: '' (static image / default),
-- 'pulse', or 'bounce' — animates while the bot is composing / speaking.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS avatar_style TEXT NOT NULL DEFAULT '';
