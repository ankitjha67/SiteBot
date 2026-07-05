"""Persistence layer: sites, chunks, pages, retrieval, conversations, leads,
handoffs, answer cache, and tenants."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pgvector.asyncpg import Vector

from sitebot.db import get_pool


@dataclass(slots=True)
class SiteRow:
    id: int
    tenant_id: int
    slug: str
    start_url: str
    display_name: str
    theme_color: str
    welcome_message: str
    status: str
    plan: str = "trial"
    allowed_origins: str = ""
    avatar_url: str = ""
    widget_position: str = "right"
    suggested_questions: list[str] = field(default_factory=list)
    lead_capture_enabled: bool = False
    lead_prompt: str = ""
    lead_webhook_url: str = ""
    handoff_enabled: bool = False
    handoff_webhook_url: str = ""
    canned_answers: list[dict[str, str]] = field(default_factory=list)
    blocked_topics: list[str] = field(default_factory=list)
    tone: str = ""
    min_confidence: float = 0.0
    hide_branding: bool = False
    last_indexed_at: Any = None
    custom_instructions: str = ""
    model_provider: str = ""
    model_name: str = ""
    history_turns: int = 6
    retention_days: int = 0
    proactive_message: str = ""
    proactive_delay_s: int = 0
    telegram_bot_token: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    followups_enabled: bool = False
    widget_language: str = "en"
    digest_webhook_url: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    guard_enabled: bool = False
    protected_secrets: list[str] = field(default_factory=list)
    protected_topics: list[str] = field(default_factory=list)
    guard_llm_audit: bool = True
    guard_refusal_message: str = "I'm sorry, but I can't share that information."
    notify_email: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    messenger_page_token: str = ""
    messenger_verify_token: str = ""
    messenger_app_secret: str = ""
    teams_app_id: str = ""
    teams_app_password: str = ""
    digest_channel: str = "webhook"
    avatar_style: str = ""
    llm_api_key: str = ""
    extra_urls: list[str] = field(default_factory=list)
    crm_provider: str = ""
    crm_api_key: str = ""
    booking_url: str = ""
    qualifying_questions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetrievedChunk:
    url: str
    title: str
    content: str
    score: float


_SITE_COLUMNS = (
    "s.id, s.tenant_id, s.slug, s.start_url, s.display_name, s.theme_color, "
    "s.welcome_message, s.status, t.plan, s.allowed_origins, s.avatar_url, "
    "s.widget_position, s.suggested_questions, s.lead_capture_enabled, s.lead_prompt, "
    "s.lead_webhook_url, s.handoff_enabled, s.handoff_webhook_url, s.canned_answers, "
    "s.blocked_topics, s.tone, s.min_confidence, s.hide_branding, s.last_indexed_at, "
    "s.custom_instructions, s.model_provider, s.model_name, s.history_turns, "
    "s.retention_days, s.proactive_message, s.proactive_delay_s, "
    "s.telegram_bot_token, s.slack_bot_token, s.slack_signing_secret, "
    "s.followups_enabled, s.widget_language, s.digest_webhook_url, "
    "s.whatsapp_token, s.whatsapp_phone_id, s.whatsapp_verify_token, s.whatsapp_app_secret, "
    "s.guard_enabled, s.protected_secrets, s.protected_topics, s.guard_llm_audit, "
    "s.guard_refusal_message, s.notify_email, s.twilio_account_sid, s.twilio_auth_token, "
    "s.twilio_from, s.messenger_page_token, s.messenger_verify_token, s.messenger_app_secret, "
    "s.teams_app_id, s.teams_app_password, s.digest_channel, s.avatar_style, "
    "s.llm_api_key, s.extra_urls, s.crm_provider, s.crm_api_key, "
    "s.booking_url, s.qualifying_questions"
)


# Columns holding client secrets, encrypted at rest (see sitebot.crypto).
SECRET_COLUMNS = (
    "llm_api_key", "telegram_bot_token", "slack_bot_token", "slack_signing_secret",
    "whatsapp_token", "whatsapp_app_secret", "twilio_auth_token",
    "teams_app_password", "messenger_page_token", "messenger_app_secret",
    "crm_api_key",
)


def _to_site(row: Any) -> SiteRow:
    from sitebot.crypto import decrypt_secret

    d = dict(row)
    for key in (
        "suggested_questions", "canned_answers", "blocked_topics",
        "protected_secrets", "protected_topics", "extra_urls",
        "qualifying_questions",
    ):
        v = d.get(key)
        if isinstance(v, str):
            d[key] = json.loads(v)
        elif v is None:
            d[key] = []
    for key in SECRET_COLUMNS:
        if d.get(key):
            d[key] = decrypt_secret(d[key])
    # Guardian values are stored element-encrypted inside the JSON list.
    d["protected_secrets"] = [decrypt_secret(s) or "" for s in d["protected_secrets"]]
    return SiteRow(**d)


async def increment_guard_blocks(site_id: int, n: int = 1) -> None:
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET guard_blocks = guard_blocks + $2 WHERE id = $1", site_id, n
    )


async def get_site_by_public_key(public_key: str) -> SiteRow | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        f"SELECT {_SITE_COLUMNS} FROM sites s JOIN tenants t ON t.id = s.tenant_id "
        "WHERE s.public_key = $1",
        public_key,
    )
    return _to_site(row) if row else None


async def get_site_by_slug(slug: str) -> SiteRow | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        f"SELECT {_SITE_COLUMNS} FROM sites s JOIN tenants t ON t.id = s.tenant_id "
        "WHERE s.slug = $1",
        slug,
    )
    return _to_site(row) if row else None


async def get_seed_urls(site_id: int) -> list[str]:
    """Primary start_url plus any additional seed URLs for this site."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT start_url, extra_urls FROM sites WHERE id = $1", site_id
    )
    if row is None:
        return []
    extra = row["extra_urls"]
    if isinstance(extra, str):
        extra = json.loads(extra)
    return [row["start_url"], *[u for u in (extra or []) if u]]


async def delete_site(site_id: int) -> None:
    """Remove a site and every row that belongs to it. Irreversible."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM handoffs WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE site_id = $1)", site_id
        )
        await conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE site_id = $1)", site_id
        )
        for table in (
            "conversations", "chunks", "pages", "answer_cache",
            "leads", "sources", "actions", "usage_events",
        ):
            await conn.execute(f"DELETE FROM {table} WHERE site_id = $1", site_id)
        await conn.execute("DELETE FROM sites WHERE id = $1", site_id)


async def delete_tenant(tenant_id: int) -> int:
    """Off-board a client completely: all their sites, keys, and the tenant
    row. Returns the number of sites removed."""
    pool = await get_pool()
    site_ids = [
        r["id"] for r in await pool.fetch(
            "SELECT id FROM sites WHERE tenant_id = $1", tenant_id
        )
    ]
    for sid in site_ids:
        await delete_site(int(sid))
    await pool.execute("DELETE FROM tenant_keys WHERE tenant_id = $1", tenant_id)
    await pool.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
    return len(site_ids)


async def export_tenant_data(tenant_id: int) -> dict:
    """Everything a client's data-portability request needs, as one JSON
    document. Secrets are exported as booleans (configured / not), never as
    values."""
    pool = await get_pool()
    tenant = await pool.fetchrow(
        "SELECT id, name, email, plan, billing_status, created_at FROM tenants WHERE id = $1",
        tenant_id,
    )
    if tenant is None:
        return {}
    sites = await pool.fetch("SELECT * FROM sites WHERE tenant_id = $1", tenant_id)
    out: dict = {
        "tenant": {**dict(tenant), "created_at": tenant["created_at"].isoformat()},
        "sites": [],
    }
    for s in sites:
        d = dict(s)
        for col in SECRET_COLUMNS:
            d[col] = bool(d.get(col))
        d["protected_secrets"] = None  # confidential by definition
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        convs = await pool.fetch(
            "SELECT id, visitor_id, created_at FROM conversations WHERE site_id = $1", s["id"]
        )
        d["conversations"] = []
        for c in convs:
            msgs = await pool.fetch(
                "SELECT role, content, answered, confidence, feedback, created_at "
                "FROM messages WHERE conversation_id = $1 ORDER BY id", c["id"]
            )
            d["conversations"].append({
                "id": c["id"], "visitor_id": c["visitor_id"],
                "created_at": c["created_at"].isoformat(),
                "messages": [
                    {**dict(m), "created_at": m["created_at"].isoformat()} for m in msgs
                ],
            })
        leads = await pool.fetch("SELECT * FROM leads WHERE site_id = $1", s["id"])
        d["leads"] = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(le).items()}
            for le in leads
        ]
        out["sites"].append(d)
    return out


async def get_site_flag(site_id: int, column: str) -> bool:
    if column not in ("render_js",):  # whitelist: column name is interpolated
        raise ValueError(column)
    pool = await get_pool()
    return bool(await pool.fetchval(f"SELECT {column} FROM sites WHERE id = $1", site_id))


async def rotate_tenant_key(tenant_id: int, key_hash: str) -> bool:
    """Replace a tenant's primary API key (used by the client-key generator)."""
    pool = await get_pool()
    updated = await pool.fetchval(
        "UPDATE tenants SET api_key_hash = $2 WHERE id = $1 RETURNING id",
        tenant_id, key_hash,
    )
    return updated is not None


async def set_site_status(site_id: int, status: str, error: str | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET status = $2, last_error = $3, updated_at = now() WHERE id = $1",
        site_id,
        status,
        error,
    )


# --------------------------- incremental indexing ---------------------------
async def get_page_hashes(site_id: int) -> dict[str, str]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT url, content_hash FROM pages WHERE site_id = $1", site_id
    )
    return {r["url"]: r["content_hash"] for r in rows}


async def apply_incremental_index(
    site_id: int,
    rows: list[tuple[str, str, str, int, list[float]]],
    changed_urls: list[str],
    removed_urls: list[str],
    page_hashes: dict[str, tuple[str, str]],
    seen_urls: list[str],
    full: bool = False,
) -> None:
    """Atomically apply one crawl's diff: replace chunks for changed URLs,
    prune removed URLs, and upsert page hashes."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        if full:
            # Only crawled content: uploaded/text/QA sources (source:// urls)
            # survive a full site re-index.
            await conn.execute(
                "DELETE FROM chunks WHERE site_id = $1 AND url LIKE 'http%'", site_id
            )
            await conn.execute("DELETE FROM pages WHERE site_id = $1", site_id)
        else:
            if changed_urls:
                await conn.execute(
                    "DELETE FROM chunks WHERE site_id = $1 AND url = ANY($2::text[])",
                    site_id, changed_urls,
                )
            if removed_urls:
                await conn.execute(
                    "DELETE FROM chunks WHERE site_id = $1 AND url = ANY($2::text[])",
                    site_id, removed_urls,
                )
                await conn.execute(
                    "DELETE FROM pages WHERE site_id = $1 AND url = ANY($2::text[])",
                    site_id, removed_urls,
                )
        if rows:
            await conn.executemany(
                "INSERT INTO chunks (site_id, url, title, content, token_count, embedding) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                [
                    (site_id, url, title, content, tok, Vector(emb))
                    for url, title, content, tok, emb in rows
                ],
            )
        if page_hashes:
            await conn.executemany(
                "INSERT INTO pages (site_id, url, content_hash, title, last_seen, last_indexed) "
                "VALUES ($1, $2, $3, $4, now(), now()) "
                "ON CONFLICT (site_id, url) DO UPDATE SET "
                "content_hash = EXCLUDED.content_hash, title = EXCLUDED.title, "
                "last_seen = now(), last_indexed = now()",
                [(site_id, url, h, title) for url, (h, title) in page_hashes.items()],
            )
        if seen_urls:
            await conn.execute(
                "UPDATE pages SET last_seen = now() "
                "WHERE site_id = $1 AND url = ANY($2::text[])",
                site_id, seen_urls,
            )


async def count_chunks(site_id: int) -> int:
    pool = await get_pool()
    return int(await pool.fetchval("SELECT count(*) FROM chunks WHERE site_id = $1", site_id))


async def finalise_index(site_id: int, pages: int, chunks: int, report: dict | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET status = 'ready', pages_indexed = $2, chunks_indexed = $3, "
        "last_error = NULL, last_crawl_report = $4, last_indexed_at = now(), "
        "updated_at = now() WHERE id = $1",
        site_id,
        pages,
        chunks,
        json.dumps(report or {}),
    )


# -------------------------------- retrieval --------------------------------
async def search_chunks(
    site_id: int,
    query_embedding: list[float],
    top_k: int,
    min_score: float,
) -> list[RetrievedChunk]:
    """Cosine-similarity search scoped to one site."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT url, title, content, 1 - (embedding <=> $2) AS score "
        "FROM chunks WHERE site_id = $1 "
        "ORDER BY embedding <=> $2 LIMIT $3",
        site_id,
        Vector(query_embedding),
        top_k,
    )
    results = [
        RetrievedChunk(
            url=r["url"], title=r["title"], content=r["content"], score=float(r["score"])
        )
        for r in rows
    ]
    return [r for r in results if r.score >= min_score]


async def keyword_fallback(site_id: int, query: str, top_k: int) -> list[RetrievedChunk]:
    """Trigram similarity fallback when vector recall is weak."""
    pool = await get_pool()
    # asyncpg passes SQL verbatim ($n placeholders, no %-escaping), so the
    # trigram match operator is a single %.
    rows = await pool.fetch(
        "SELECT url, title, content, similarity(content, $2) AS score "
        "FROM chunks WHERE site_id = $1 AND content % $2 "
        "ORDER BY score DESC LIMIT $3",
        site_id,
        query,
        top_k,
    )
    return [
        RetrievedChunk(
            url=r["url"], title=r["title"], content=r["content"], score=float(r["score"])
        )
        for r in rows
    ]


# ------------------------ conversations and analytics ------------------------
async def log_message(
    site_id: int,
    tenant_id: int,
    visitor_id: str | None,
    conversation_id: int | None,
    user_text: str,
    assistant_text: str,
    sources: list[dict[str, str]],
    answered: bool = True,
    confidence: float | None = None,
) -> int:
    """Persist a turn and a usage event. Returns the conversation id."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        if conversation_id is None:
            conversation_id = await conn.fetchval(
                "INSERT INTO conversations (site_id, visitor_id) VALUES ($1, $2) RETURNING id",
                site_id,
                visitor_id,
            )
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'user', $2)",
            conversation_id,
            user_text,
        )
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, answered, confidence) "
            "VALUES ($1, 'assistant', $2, $3, $4, $5)",
            conversation_id,
            assistant_text,
            json.dumps(sources),
            answered,
            confidence,
        )
        await conn.execute(
            "INSERT INTO usage_events (tenant_id, site_id, kind) VALUES ($1, $2, 'message')",
            tenant_id,
            site_id,
        )
    return conversation_id


async def record_feedback(conversation_id: int, message_index: int, value: int) -> bool:
    """Store visitor feedback on the Nth assistant message of a conversation."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM messages WHERE conversation_id = $1 AND role = 'assistant' "
        "ORDER BY id OFFSET $2 LIMIT 1",
        conversation_id,
        message_index,
    )
    if row is None:
        return False
    await pool.execute("UPDATE messages SET feedback = $2 WHERE id = $1", row["id"], value)
    return True


# ------------------------------ leads, handoffs ------------------------------
async def create_lead(
    site_id: int,
    conversation_id: int | None,
    email: str,
    name: str,
    note: str,
    visitor_id: str | None,
) -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "INSERT INTO leads (site_id, conversation_id, email, name, note, visitor_id) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            site_id, conversation_id, email, name, note, visitor_id,
        )
    )


async def create_handoff(
    site_id: int,
    conversation_id: int | None,
    email: str,
    message: str,
    visitor_id: str | None,
) -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "INSERT INTO handoffs (site_id, conversation_id, email, message, visitor_id) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            site_id, conversation_id, email, message, visitor_id,
        )
    )


# -------------------------------- answer cache --------------------------------
async def cache_get(site_id: int, question_hash: str, ttl_s: int) -> dict | None:
    if ttl_s <= 0:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT answer, sources FROM answer_cache "
        "WHERE site_id = $1 AND question_hash = $2 "
        "AND created_at > now() - ($3 || ' seconds')::interval",
        site_id,
        question_hash,
        str(ttl_s),
    )
    if row is None:
        return None
    sources = row["sources"]
    return {
        "answer": row["answer"],
        "sources": json.loads(sources) if isinstance(sources, str) else sources,
    }


async def semantic_cache_get(
    site_id: int, query_vec: list[float], ttl_s: int, threshold: float
) -> dict | None:
    """Cache hit for a question that MEANS the same, even phrased differently."""
    if ttl_s <= 0 or threshold <= 0:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT answer, sources, 1 - (question_embedding <=> $2::vector) AS sim "
        "FROM answer_cache "
        "WHERE site_id = $1 AND question_embedding IS NOT NULL "
        "AND created_at > now() - ($3 || ' seconds')::interval "
        "ORDER BY question_embedding <=> $2::vector LIMIT 1",
        site_id, query_vec, str(ttl_s),
    )
    if row is None or float(row["sim"]) < threshold:
        return None
    sources = row["sources"]
    return {
        "answer": row["answer"],
        "sources": json.loads(sources) if isinstance(sources, str) else (sources or []),
    }


async def cache_put(
    site_id: int, question_hash: str, answer: str, sources: list[dict[str, str]],
    query_vec: list[float] | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO answer_cache (site_id, question_hash, answer, sources, question_embedding) "
        "VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (site_id, question_hash) DO UPDATE SET "
        "answer = EXCLUDED.answer, sources = EXCLUDED.sources, "
        "question_embedding = EXCLUDED.question_embedding, created_at = now()",
        site_id,
        question_hash,
        answer,
        json.dumps(sources),
        query_vec,
    )


async def invalidate_cache(site_id: int) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM answer_cache WHERE site_id = $1", site_id)


# ---------------------------- conversation memory ----------------------------
async def get_history(conversation_id: int, turns: int) -> list[dict[str, str]]:
    """Last N user/assistant turns of a conversation, oldest first."""
    if turns <= 0:
        return []
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT role, content FROM messages "
        "WHERE conversation_id = $1 AND role IN ('user', 'assistant') "
        "ORDER BY id DESC LIMIT $2",
        conversation_id,
        turns * 2,
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ------------------------- knowledge sources browser -------------------------
async def create_source(site_id: int, kind: str, title: str, ref: str, chars: int) -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "INSERT INTO sources (site_id, kind, title, ref, chars) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            site_id, kind, title, ref, chars,
        )
    )


async def list_sources(site_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT s.id, s.kind, s.title, s.ref, s.chars, s.created_at, "
        "  (SELECT count(*) FROM chunks c WHERE c.site_id = s.site_id AND c.url = s.ref) AS chunks "
        "FROM sources s WHERE s.site_id = $1 ORDER BY s.id DESC",
        site_id,
    )
    return [
        {
            "id": int(r["id"]), "kind": r["kind"], "title": r["title"], "ref": r["ref"],
            "chars": int(r["chars"]), "chunks": int(r["chunks"]),
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def delete_source(site_id: int, source_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        ref = await conn.fetchval(
            "DELETE FROM sources WHERE site_id = $1 AND id = $2 RETURNING ref",
            site_id, source_id,
        )
        if ref is None:
            return False
        await conn.execute("DELETE FROM chunks WHERE site_id = $1 AND url = $2", site_id, ref)
    return True


async def list_indexed_pages(site_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT p.url, p.title, p.last_indexed, "
        "  (SELECT count(*) FROM chunks c WHERE c.site_id = p.site_id AND c.url = p.url) AS chunks "
        "FROM pages p WHERE p.site_id = $1 ORDER BY p.url",
        site_id,
    )
    return [
        {
            "url": r["url"], "title": r["title"], "chunks": int(r["chunks"]),
            "last_indexed": r["last_indexed"].isoformat() if r["last_indexed"] else None,
        }
        for r in rows
    ]


async def delete_indexed_page(site_id: int, url: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        deleted = await conn.fetchval(
            "DELETE FROM pages WHERE site_id = $1 AND url = $2 RETURNING id", site_id, url
        )
        await conn.execute("DELETE FROM chunks WHERE site_id = $1 AND url = $2", site_id, url)
    return deleted is not None


# ------------------------------ live agent inbox ------------------------------
async def add_agent_message(site_id: int, conversation_id: int, text: str) -> int | None:
    """Insert a human reply into a conversation. Returns the message id."""
    pool = await get_pool()
    owned = await pool.fetchval(
        "SELECT id FROM conversations WHERE id = $1 AND site_id = $2", conversation_id, site_id
    )
    if owned is None:
        return None
    return int(
        await pool.fetchval(
            "INSERT INTO messages (conversation_id, role, content) "
            "VALUES ($1, 'agent', $2) RETURNING id",
            conversation_id, text,
        )
    )


async def agent_messages_after(
    site_id: int, conversation_id: int, after_id: int
) -> list[dict[str, Any]]:
    """Agent replies newer than after_id — polled by the widget."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT m.id, m.content, m.created_at FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id "
        "WHERE c.site_id = $1 AND m.conversation_id = $2 AND m.role = 'agent' AND m.id > $3 "
        "ORDER BY m.id",
        site_id, conversation_id, after_id,
    )
    return [
        {"id": int(r["id"]), "content": r["content"], "at": r["created_at"].isoformat()}
        for r in rows
    ]


# ------------------------------ retention purge ------------------------------
async def purge_expired_conversations() -> int:
    """Delete conversations older than each site's retention window."""
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM conversations c USING sites s "
        "WHERE c.site_id = s.id AND s.retention_days > 0 "
        "AND c.created_at < now() - (s.retention_days || ' days')::interval"
    )
    return int(result.split()[-1]) if result else 0


# --------------------------------- export ---------------------------------
async def export_conversations(site_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT m.conversation_id, c.visitor_id, m.role, m.content, m.feedback, m.created_at "
        "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE c.site_id = $1 ORDER BY m.conversation_id, m.id",
        site_id,
    )
    return [
        {
            "conversation_id": int(r["conversation_id"]), "visitor_id": r["visitor_id"] or "",
            "role": r["role"], "content": r["content"], "feedback": r["feedback"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


# ---------------------------- channel conversations ----------------------------
async def latest_conversation_for_visitor(site_id: int, visitor_id: str) -> int | None:
    """Continue an existing thread for a channel visitor (Telegram chat,
    Slack user) instead of starting fresh on every message."""
    pool = await get_pool()
    row = await pool.fetchval(
        "SELECT id FROM conversations WHERE site_id = $1 AND visitor_id = $2 "
        "ORDER BY id DESC LIMIT 1",
        site_id, visitor_id,
    )
    return int(row) if row is not None else None


# ------------------------------- team keys -------------------------------
async def create_tenant_key(tenant_id: int, name: str, key_hash: str, role: str) -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "INSERT INTO tenant_keys (tenant_id, name, key_hash, role) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            tenant_id, name, key_hash, role,
        )
    )


async def list_tenant_keys(tenant_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, name, role, created_at, last_used_at FROM tenant_keys "
        "WHERE tenant_id = $1 ORDER BY id",
        tenant_id,
    )
    return [
        {
            "id": int(r["id"]), "name": r["name"], "role": r["role"],
            "created_at": r["created_at"].isoformat(),
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
        }
        for r in rows
    ]


async def revoke_tenant_key(tenant_id: int, key_id: int) -> bool:
    pool = await get_pool()
    deleted = await pool.fetchval(
        "DELETE FROM tenant_keys WHERE tenant_id = $1 AND id = $2 RETURNING id",
        tenant_id, key_id,
    )
    return deleted is not None


async def find_tenant_key(key_hash: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, tenant_id, role FROM tenant_keys WHERE key_hash = $1", key_hash
    )
    if row is None:
        return None
    await pool.execute("UPDATE tenant_keys SET last_used_at = now() WHERE id = $1", row["id"])
    return {"tenant_id": int(row["tenant_id"]), "role": row["role"]}


async def sites_with_digest() -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, slug, digest_webhook_url, digest_channel, notify_email FROM sites "
        "WHERE (digest_channel = 'webhook' AND digest_webhook_url <> '') "
        "   OR (digest_channel = 'email' AND notify_email <> '')"
    )
    return [dict(r) for r in rows]


# --------------------------------- actions ---------------------------------
async def list_actions(site_id: int, enabled_only: bool = False) -> list[dict[str, Any]]:
    pool = await get_pool()
    where = "site_id = $1" + (" AND enabled" if enabled_only else "")
    rows = await pool.fetch(
        f"SELECT id, name, description, kind, method, url, headers, params, enabled "
        f"FROM actions WHERE {where} ORDER BY id",
        site_id,
    )
    out = []
    for r in rows:
        d = dict(r)
        for jkey in ("headers", "params"):
            if isinstance(d[jkey], str):
                d[jkey] = json.loads(d[jkey])
        d["id"] = int(d["id"])
        out.append(d)
    return out


async def create_action(
    site_id: int, name: str, description: str, kind: str, method: str,
    url: str, headers: dict[str, str], params: list[dict[str, Any]],
) -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "INSERT INTO actions (site_id, name, description, kind, method, url, headers, params) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            site_id, name, description, kind, method, url,
            json.dumps(headers), json.dumps(params),
        )
    )


async def set_action_enabled(site_id: int, action_id: int, enabled: bool) -> bool:
    pool = await get_pool()
    updated = await pool.fetchval(
        "UPDATE actions SET enabled = $3 WHERE site_id = $1 AND id = $2 RETURNING id",
        site_id, action_id, enabled,
    )
    return updated is not None


async def delete_action(site_id: int, action_id: int) -> bool:
    pool = await get_pool()
    deleted = await pool.fetchval(
        "DELETE FROM actions WHERE site_id = $1 AND id = $2 RETURNING id", site_id, action_id
    )
    return deleted is not None


# --------------------------------- tenants ---------------------------------
async def create_tenant(name: str, email: str, plan: str, api_key_hash: str) -> int:
    pool = await get_pool()
    return int(
        await pool.fetchval(
            "INSERT INTO tenants (name, email, plan, api_key_hash) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            name, email, plan, api_key_hash,
        )
    )
