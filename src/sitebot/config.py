"""Central configuration loaded from environment or a .env file."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbedProvider = Literal["openai", "local"]
AnswerProvider = Literal["anthropic", "openai", "gemini", "openai_compatible"]

# Monthly answered-message quotas per plan. 0 means unlimited.
DEFAULT_PLAN_QUOTAS: dict[str, int] = {
    "free": 100,
    "trial": 300,
    "starter": 2000,
    "growth": 10000,
    "business": 40000,
    "enterprise": 0,
}


class Settings(BaseSettings):
    """Runtime configuration. Override any field via environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = Field(
        default="postgresql://sitebot:sitebot@localhost:5432/sitebot",
        description="PostgreSQL DSN. The database must have the pgvector extension.",
    )

    # Redis powers the job queue, rate limiting, and scheduled re-crawls.
    # Empty falls back to in-process equivalents (single-instance dev mode).
    redis_url: str = Field(default="")

    # Connection pool. Size max for your workload: roughly
    # (concurrent chat requests you expect) but below Postgres max_connections
    # divided by API worker processes.
    db_pool_min: int = Field(default=2)
    db_pool_max: int = Field(default=20)

    # Global admin auth. Rotate this. Tenants get their own scoped keys.
    admin_api_key: str = Field(default="change-me-admin-key")

    # Encrypts client secrets (per-site LLM keys, channel tokens, Guardian
    # values) at rest. Any string; stretched to a Fernet key. REQUIRED in
    # production - without it secrets are stored in plaintext.
    secret_encryption_key: str = Field(default="")

    # LLM (answer generation). Provider seam: anthropic (default), openai,
    # gemini, or openai_compatible (Ollama/Groq/Together/vLLM/... via base URL).
    # ANSWER_MODEL must be a model the chosen provider serves.
    answer_provider: AnswerProvider = Field(default="anthropic")
    anthropic_api_key: str = Field(default="")
    answer_model: str = Field(default="claude-haiku-4-5")
    answer_max_tokens: int = Field(default=700)
    gemini_api_key: str = Field(default="")
    # For openai_compatible: e.g. http://localhost:11434/v1 (Ollama),
    # https://api.groq.com/openai/v1, https://api.together.xyz/v1 ...
    openai_compatible_base_url: str = Field(default="")
    openai_compatible_api_key: str = Field(default="")

    # Embeddings
    embed_provider: EmbedProvider = Field(default="openai")
    openai_api_key: str = Field(default="")
    openai_embed_model: str = Field(default="text-embedding-3-small")
    local_embed_model: str = Field(default="BAAI/bge-small-en-v1.5")
    # Must match the model above. text-embedding-3-small = 1536, bge-small = 384.
    embed_dim: int = Field(default=1536)

    # Crawler
    max_pages: int = Field(default=200)
    request_timeout_s: float = Field(default=20.0)
    crawl_delay_s: float = Field(default=0.3)
    crawl_concurrency: int = Field(default=4, description="Concurrent page fetches per crawl.")
    user_agent: str = Field(default="SiteBot/0.1 (+https://example.com/bot)")
    use_browser: bool = Field(default=False, description="Render JS pages with Playwright.")

    # Local embedding: bound concurrent encodes so a burst of chat requests
    # cannot thrash the CPU. Hosted providers are unaffected.
    embed_concurrency: int = Field(default=2)

    # Chunking (approximate token targets; ~4 chars per token)
    chunk_chars: int = Field(default=3200)
    chunk_overlap_chars: int = Field(default=500)

    # Retrieval
    top_k: int = Field(default=6)
    min_score: float = Field(default=0.0, description="Cosine similarity floor (0..1).")
    # Cross-encoder re-ranking: retrieve wide, re-rank to top_k. Downloads a
    # ~90 MB model on first use; adds ~50-150 ms/query on CPU.
    rerank_enabled: bool = Field(default=False)
    # Agentic retrieval: max retrieve->assess->refine iterations per question.
    agentic_max_iters: int = Field(default=2)
    rerank_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    # Rewrite follow-up questions into standalone queries before retrieval
    # ("how much is it?" -> "how much does the starter plan cost?").
    query_rewrite_enabled: bool = Field(default=True)
    # Semantic cache: serve cached answers for questions phrased differently
    # but meaning the same (cosine >= threshold). 0 disables.
    semantic_cache_threshold: float = Field(default=0.97)
    # Cost routing: answer easy questions (short, high retrieval confidence)
    # with a cheaper model. Empty = always use the site's configured model.
    cheap_model_name: str = Field(default="")
    cheap_model_confidence: float = Field(default=0.78)

    # Answer cache. 0 disables. Serving repeats from cache protects gross margin.
    answer_cache_ttl_s: int = Field(default=86400)

    # Rate limiting (per public key + client IP)
    rate_limit_per_minute: int = Field(default=30)

    # Plan quotas as JSON, e.g. '{"free":100,"starter":2000}'. 0 = unlimited.
    plan_quotas_json: str = Field(default="")

    # Serving
    cors_origins: str = Field(default="*", description="Comma separated. Lock down in production.")
    # Public HTTPS base URL of this API (e.g. https://api.yourdomain.com).
    # Needed for channel webhooks (Telegram setWebhook). Empty = manual setup.
    public_base_url: str = Field(default="")

    # Email (SMTP) for lead/handoff alerts and digests. Platform-level relay;
    # each site sets its own recipient address. Empty host disables email.
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="SiteBot <bot@example.com>")
    smtp_use_tls: bool = Field(default=True, description="STARTTLS (587). False for plain/SSL.")

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)

    # Observability
    log_json: bool = Field(default=True, description="Emit JSON logs (set false for dev).")
    log_level: str = Field(default="INFO")
    sentry_dsn: str = Field(default="", description="Enable Sentry error tracking if set.")

    # Billing (Phase 3). All optional; billing endpoints no-op without them.
    stripe_secret_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="")

    # Razorpay (India). Optional; endpoints 503 without a key id + secret.
    razorpay_key_id: str = Field(default="")
    razorpay_key_secret: str = Field(default="")
    razorpay_webhook_secret: str = Field(default="")
    billing_currency: str = Field(default="usd", description="usd or inr.")
    # Map of Stripe price id -> plan name, JSON. e.g. '{"price_123":"starter"}'
    stripe_price_map_json: str = Field(default="")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def plan_quotas(self) -> dict[str, int]:
        if not self.plan_quotas_json:
            return DEFAULT_PLAN_QUOTAS
        merged = dict(DEFAULT_PLAN_QUOTAS)
        merged.update({k: int(v) for k, v in json.loads(self.plan_quotas_json).items()})
        return merged

    @property
    def stripe_price_map(self) -> dict[str, str]:
        if not self.stripe_price_map_json:
            return {}
        return dict(json.loads(self.stripe_price_map_json))


@lru_cache
def get_settings() -> Settings:
    return Settings()
