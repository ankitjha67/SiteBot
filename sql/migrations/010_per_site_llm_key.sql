-- Per-client LLM API key: each site can bring its own answer-model key
-- (mandatory in the onboarding wizard unless using a local/OpenAI-compatible
-- model). Stored server-side only; never returned by any read endpoint.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS llm_api_key TEXT NOT NULL DEFAULT '';
