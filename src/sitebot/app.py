"""FastAPI application: tenant and site management, ingestion, analytics,
leads, handoffs, billing, the admin dashboard, and the public chat API."""

from __future__ import annotations

import json
import logging
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from sitebot import analytics, billing, channels, email_out, store, webhooks
from sitebot import sources as sources_mod
from sitebot.auth import (
    AuthContext,
    authorize_site,
    ensure_writer,
    generate_tenant_key,
    require_admin,
    require_auth,
    require_feature,
)
from sitebot.config import get_settings
from sitebot.crypto import encrypt_secret
from sitebot.db import apply_schema, check_ready, close_pool, get_pool
from sitebot.ingest import ingest_site
from sitebot.logging_setup import RequestContextMiddleware, setup_logging
from sitebot.rag import answer_stream
from sitebot.ratelimit import enforce_monthly_quota, enforce_rate_limit
from sitebot.store import SiteRow, get_site_by_public_key

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
# Repo layout (editable install) or the container WORKDIR (pip install .).
_WIDGET_DIR = Path(__file__).resolve().parents[2] / "widget"
if not _WIDGET_DIR.exists():
    _WIDGET_DIR = Path.cwd() / "widget"

_arq_pool: Any = None


@asynccontextmanager
async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
    setup_logging(get_settings())
    s = get_settings()
    if s.admin_api_key in ("change-me-admin-key", "dev-admin-key") or len(s.admin_api_key) < 16:
        log.warning(
            "SECURITY: ADMIN_API_KEY is a default or short value — set a strong, "
            "unique key before exposing this service."
        )
    if "*" in s.cors_origin_list:
        log.warning(
            "SECURITY: CORS_ORIGINS is '*' — lock it to your customer domains in production."
        )
    await apply_schema()
    yield
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
    await close_pool()


app = FastAPI(title="SiteBot", version="0.2.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------ ingest queueing ------------------------------
async def _run_ingest_inline(site_id: int, start_url: str, full: bool) -> None:
    try:
        await ingest_site(site_id, start_url, settings, full=full)
    except Exception as exc:  # noqa: BLE001
        log.exception("inline ingest failed for site %s", site_id)
        await store.set_site_status(site_id, "error", str(exc)[:500])


async def _enqueue_ingest(
    site_id: int, start_url: str, tasks: BackgroundTasks, full: bool = False
) -> str:
    """Queue on the arq worker when Redis is configured; else run in-process."""
    global _arq_pool
    if settings.redis_url:
        if _arq_pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await _arq_pool.enqueue_job("ingest_site_task", site_id, start_url, full)
        return "queued"
    tasks.add_task(_run_ingest_inline, site_id, start_url, full)
    return "started"


def _check_origin(site: SiteRow, request: Request) -> None:
    """Per-site CORS: when allowed_origins is set, browser calls must match."""
    allowed = [o.strip().rstrip("/") for o in site.allowed_origins.split(",") if o.strip()]
    if not allowed:
        return
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin not allowed for this site.")


# ----------------------------- request models -----------------------------
class CreateTenant(BaseModel):
    name: str
    email: str = ""
    plan: str = "trial"


class Signup(BaseModel):
    name: str
    email: EmailStr


class CreateSite(BaseModel):
    name: str
    start_url: str
    slug: str | None = None
    display_name: str = "Assistant"
    theme_color: str = "#4f46e5"
    welcome_message: str = "Hi. Ask me anything about this site."
    tenant_id: int | None = None  # admin only; tenant keys use their own


class UpdateSite(BaseModel):
    """Everything a customer can self-serve tune. All fields optional."""

    start_url: str | None = None
    display_name: str | None = None
    theme_color: str | None = None
    welcome_message: str | None = None
    avatar_url: str | None = None
    widget_position: str | None = Field(default=None, pattern="^(left|right)$")
    suggested_questions: list[str] | None = None
    allowed_origins: str | None = None
    extra_urls: list[str] | None = None
    recrawl_hours: int | None = Field(default=None, ge=0)
    render_js: bool | None = None
    crm_provider: str | None = Field(default=None, pattern="^(hubspot|pipedrive|webhook|)$")
    crm_api_key: str | None = None
    booking_url: str | None = None
    qualifying_questions: list[str] | None = None
    widget_font: str | None = None
    widget_font_url: str | None = None
    retrieval_mode: str | None = Field(default=None, pattern="^(hybrid|agentic)$")
    answer_mode: str | None = Field(default=None, pattern="^(llm|extractive)$")
    fallback_extractive: bool | None = None
    lead_capture_enabled: bool | None = None
    lead_prompt: str | None = None
    lead_webhook_url: str | None = None
    handoff_enabled: bool | None = None
    handoff_webhook_url: str | None = None
    canned_answers: list[dict[str, str]] | None = None
    blocked_topics: list[str] | None = None
    tone: str | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    hide_branding: bool | None = None
    custom_instructions: str | None = None
    model_provider: str | None = Field(
        default=None, pattern="^(|anthropic|openai|gemini|openai_compatible)$"
    )
    model_name: str | None = None
    history_turns: int | None = Field(default=None, ge=0, le=20)
    retention_days: int | None = Field(default=None, ge=0)
    proactive_message: str | None = None
    proactive_delay_s: int | None = Field(default=None, ge=0)
    followups_enabled: bool | None = None
    widget_language: str | None = Field(default=None, pattern="^(en|es|fr|de|hi|pt)$")
    digest_webhook_url: str | None = None
    slack_bot_token: str | None = None
    slack_signing_secret: str | None = None
    guard_enabled: bool | None = None
    protected_secrets: list[str] | None = None
    protected_topics: list[str] | None = None
    guard_llm_audit: bool | None = None
    guard_refusal_message: str | None = None
    notify_email: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from: str | None = None
    messenger_page_token: str | None = None
    messenger_verify_token: str | None = None
    messenger_app_secret: str | None = None
    teams_app_id: str | None = None
    teams_app_password: str | None = None
    digest_channel: str | None = Field(default=None, pattern="^(webhook|email)$")
    avatar_style: str | None = Field(default=None, pattern="^(|pulse|bounce)$")
    # Write-only credentials (set here for one-shot onboarding; never returned).
    llm_api_key: str | None = None
    telegram_bot_token: str | None = None
    whatsapp_token: str | None = None
    whatsapp_phone_id: str | None = None
    whatsapp_verify_token: str | None = None
    whatsapp_app_secret: str | None = None


class ChatRequest(BaseModel):
    key: str = Field(description="The site public key.")
    message: str
    visitor_id: str | None = None
    conversation_id: int | None = None


class FeedbackRequest(BaseModel):
    key: str
    conversation_id: int
    message_index: int = Field(ge=0, description="0-based index of the assistant message.")
    value: int = Field(description="1 = helpful, -1 = not helpful.")


class LeadRequest(BaseModel):
    key: str
    email: EmailStr
    name: str = ""
    note: str = ""
    conversation_id: int | None = None
    visitor_id: str | None = None
    # Answers to the site's qualifying questions: {question: answer}.
    qualification: dict[str, str] | None = None


class HandoffRequest(BaseModel):
    key: str
    email: str = ""
    message: str = ""
    conversation_id: int | None = None
    visitor_id: str | None = None


class CheckoutRequest(BaseModel):
    price_id: str
    success_url: str
    cancel_url: str


class SourceCreate(BaseModel):
    """Raw text or a Q&A pair as a knowledge source."""

    kind: str = Field(pattern="^(text|qa)$")
    title: str = ""
    text: str = ""       # kind=text
    question: str = ""   # kind=qa
    answer: str = ""     # kind=qa


class PlaygroundRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ReplyRequest(BaseModel):
    message: str


class TeamKeyCreate(BaseModel):
    name: str
    role: str = Field(default="admin", pattern="^(admin|viewer)$")


class TelegramSetup(BaseModel):
    bot_token: str


class OnboardRequest(BaseModel):
    """One-shot client setup: create a site and apply every setting at once.
    Mandatory: name, start_url, and an answer model the site can actually call
    (a per-site LLM key, or a local/OpenAI-compatible provider, or a
    platform-configured key for the chosen provider)."""

    name: str = Field(min_length=1)
    start_url: str = Field(min_length=4)
    slug: str | None = None
    tenant_id: int | None = None       # admin only
    ingest_now: bool = True
    config: UpdateSite = Field(default_factory=UpdateSite)


class WhatsAppSetup(BaseModel):
    token: str
    phone_id: str
    verify_token: str
    app_secret: str = ""


class ActionCreate(BaseModel):
    name: str = Field(pattern="^[a-z0-9_]{2,40}$")
    description: str
    kind: str = Field(default="http", pattern="^(http|link)$")
    method: str = Field(default="GET", pattern="^(GET|POST)$")
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: list[dict[str, Any]] = Field(default_factory=list)


class ActionToggle(BaseModel):
    enabled: bool


# ------------------------------- tenants API -------------------------------
@app.post("/v1/tenants")
async def create_tenant(
    body: CreateTenant, _: Annotated[AuthContext, Depends(require_admin)]
) -> dict:
    key, key_hash = generate_tenant_key()
    tenant_id = await store.create_tenant(body.name, body.email, body.plan, key_hash)
    return {"tenant_id": tenant_id, "api_key": key, "plan": body.plan,
            "note": "Store this key now; it is not shown again."}


@app.post("/v1/signup")
async def signup(body: Signup, request: Request) -> dict:
    """Self-serve signup (Phase 3): creates a free-plan tenant and returns its key."""
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(f"signup:{client_ip}", settings)
    key, key_hash = generate_tenant_key()
    tenant_id = await store.create_tenant(body.name, str(body.email), "free", key_hash)
    return {"tenant_id": tenant_id, "api_key": key, "plan": "free",
            "note": "Store this key now; it is not shown again."}


@app.get("/v1/tenants/me")
async def tenant_me(ctx: Annotated[AuthContext, Depends(require_auth)]) -> dict:
    if ctx.tenant_id is None:
        return {"is_admin": True}
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, email, plan, billing_status, created_at FROM tenants WHERE id = $1",
        ctx.tenant_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    used = await billing.usage_this_month(ctx.tenant_id)
    quota = settings.plan_quotas.get(row["plan"], 0)
    return {
        "tenant_id": int(row["id"]), "name": row["name"], "email": row["email"],
        "plan": row["plan"], "billing_status": row["billing_status"],
        "messages_used_this_month": used,
        "monthly_quota": quota or None,
    }


# ------------------------------- sites API --------------------------------
@app.post("/v1/sites")
async def create_site(
    body: CreateSite, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    slug = body.slug or urlparse(body.start_url).netloc.replace(".", "-").lower()
    if not slug:
        raise HTTPException(status_code=400, detail="Could not derive a slug from start_url.")
    public_key = "pk_" + secrets.token_urlsafe(24)
    pool = await get_pool()

    client_api_key: str | None = None
    if ctx.tenant_id is not None:
        tenant_id = ctx.tenant_id
    elif body.tenant_id is not None:
        tenant_id = body.tenant_id
    else:
        # Back-compat convenience: admin creates a site without a tenant ->
        # a tenant is created implicitly with the same name. Return its key
        # once so the operator can hand the client dashboard access.
        client_api_key, key_hash = generate_tenant_key()
        tenant_id = await store.create_tenant(body.name, "", "trial", key_hash)

    try:
        site_id = await pool.fetchval(
            "INSERT INTO sites (tenant_id, slug, start_url, public_key, display_name, "
            "theme_color, welcome_message) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id",
            tenant_id, slug, body.start_url, public_key, body.display_name,
            body.theme_color, body.welcome_message,
        )
    except Exception as exc:  # unique violation on slug
        raise HTTPException(status_code=409, detail=f"Slug already exists: {slug}") from exc
    return {"site_id": site_id, "slug": slug, "public_key": public_key,
            "status": "new", "client_api_key": client_api_key}


@app.post("/v1/onboard")
async def onboard(
    body: OnboardRequest, tasks: BackgroundTasks,
    ctx: Annotated[AuthContext, Depends(require_auth)],
) -> dict:
    """Create a client site and apply the full configuration in one call, with
    mandatory-field enforcement so an unusable bot can't be created."""
    ensure_writer(ctx)
    cfg = body.config

    # --- mandatory: a working answer model ---
    provider = cfg.model_provider or settings.answer_provider
    platform_key = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "openai_compatible": settings.openai_compatible_api_key or "local",
    }.get(provider, "")
    if provider != "openai_compatible" and not (cfg.llm_api_key or platform_key):
        raise HTTPException(
            status_code=400,
            detail=(
                f"An LLM API key is required for provider '{provider}'. Enter the "
                "client's key, or choose a local (OpenAI-compatible) model."
            ),
        )

    # --- derive slug + default the widget origin lock to the client's domain ---
    parsed = urlparse(body.start_url if "://" in body.start_url else "https://" + body.start_url)
    slug = body.slug or parsed.netloc.replace(".", "-").lower()
    if not slug:
        raise HTTPException(status_code=400, detail="Could not derive a slug from the domain.")
    start_url = body.start_url if "://" in body.start_url else "https://" + body.start_url
    if cfg.allowed_origins is None and parsed.netloc:
        cfg.allowed_origins = f"https://{parsed.netloc}"

    # --- tenant resolution (same rules as create_site) ---
    # client_api_key is the new client's login/dashboard key — returned exactly
    # once so the operator can hand it over. Null when reusing an existing tenant.
    client_api_key: str | None = None
    if ctx.tenant_id is not None:
        tenant_id = ctx.tenant_id
    elif body.tenant_id is not None:
        tenant_id = body.tenant_id
    else:
        client_api_key, key_hash = generate_tenant_key()
        tenant_id = await store.create_tenant(body.name, "", "trial", key_hash)

    public_key = "pk_" + secrets.token_urlsafe(24)
    pool = await get_pool()
    try:
        site_id = await pool.fetchval(
            "INSERT INTO sites (tenant_id, slug, start_url, public_key, display_name) "
            "VALUES ($1,$2,$3,$4,$5) RETURNING id",
            tenant_id, slug, start_url, public_key, cfg.display_name or body.name,
        )
    except Exception as exc:  # unique violation on slug
        raise HTTPException(status_code=409, detail=f"A site already exists: {slug}") from exc

    # --- apply every provided setting in one shot ---
    await _apply_site_updates(int(site_id), cfg.model_dump(exclude_none=True))

    # --- optional: auto-register the Telegram webhook if a token was given ---
    if cfg.telegram_bot_token and settings.public_base_url:
        webhook_url = (
            settings.public_base_url.rstrip("/") + "/v1/channels/telegram/" + public_key
        )
        try:
            await channels.set_telegram_webhook(cfg.telegram_bot_token, webhook_url)
        except Exception:  # noqa: BLE001 - non-fatal; can be retried from the dashboard
            log.warning("telegram webhook registration failed during onboarding")

    status = "new"
    if body.ingest_now:
        status = await _enqueue_ingest(int(site_id), start_url, tasks)

    origin = settings.public_base_url.rstrip("/") if settings.public_base_url else ""
    snippet = (
        f'<script src="{origin}/widget.js"\n'
        f'        data-key="{public_key}"\n'
        f'        data-api="{origin}"></script>'
    )
    return {
        "site_id": int(site_id), "slug": slug, "public_key": public_key,
        "status": status, "embed_snippet": snippet,
        "client_api_key": client_api_key,
    }


class RegisterUser(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    role: str = Field(default="admin", pattern="^(admin|viewer)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/v1/auth/register")
async def register_user(
    body: RegisterUser, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    """Create an email+password login for the caller's tenant. Requires an
    existing credential (the client's API key, or a logged-in admin user) so
    strangers can't attach accounts to a tenant."""
    ensure_writer(ctx)
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant credential to add users.")
    from sitebot.auth import hash_password
    pool = await get_pool()
    try:
        user_id = await pool.fetchval(
            "INSERT INTO tenant_users (tenant_id, email, password_hash, role) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            ctx.tenant_id, body.email.lower(), hash_password(body.password), body.role,
        )
    except Exception as exc:  # unique violation on email
        raise HTTPException(status_code=409, detail="That email already has an account.") from exc
    return {"user_id": int(user_id), "email": body.email.lower(), "role": body.role}


@app.post("/v1/auth/login")
async def login(body: LoginRequest, request: Request) -> dict:
    from sitebot.auth import create_session, verify_password
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(f"login:{client_ip}", settings)  # brute-force brake
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, password_hash FROM tenant_users WHERE email = $1", body.email.lower()
    )
    # Constant-shaped failure: never reveal whether the email exists.
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    await pool.execute(
        "UPDATE tenant_users SET last_login = now() WHERE id = $1", row["id"]
    )
    token = await create_session(int(row["id"]))
    return {"session_token": token, "note": "Send as X-API-Key. Valid 14 days."}


@app.post("/v1/auth/logout")
async def logout(x_api_key: Annotated[str, Header()] = "") -> dict:
    from sitebot.auth import hash_key
    if x_api_key.startswith("st_"):
        pool = await get_pool()
        await pool.execute(
            "DELETE FROM user_sessions WHERE token_hash = $1", hash_key(x_api_key)
        )
    return {"ok": True}


def _csv(rows: list[dict], columns: list[str]) -> Response:
    import csv as _csvmod
    import io
    buf = io.StringIO()
    w = _csvmod.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in columns})
    return Response(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="report.csv"'},
    )


@app.get("/v1/sites/{slug}/reports/conversations.csv")
async def report_conversations(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], days: int = 30
) -> Response:
    require_feature(ctx, "analytics_pro")
    site = await authorize_site(ctx, slug)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT c.id AS conversation_id, c.visitor_id, m.role, m.content, "
        "m.answered, m.confidence, m.feedback, m.created_at "
        "FROM conversations c JOIN messages m ON m.conversation_id = c.id "
        "WHERE c.site_id = $1 AND m.created_at > now() - ($2 || ' days')::interval "
        "ORDER BY c.id, m.id", int(site["id"]), str(days),
    )
    return _csv(
        [dict(r) | {"created_at": r["created_at"].isoformat()} for r in rows],
        ["conversation_id", "visitor_id", "role", "content",
         "answered", "confidence", "feedback", "created_at"],
    )


@app.get("/v1/sites/{slug}/reports/leads.csv")
async def report_leads(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], days: int = 90
) -> Response:
    require_feature(ctx, "analytics_pro")
    site = await authorize_site(ctx, slug)
    pool = await get_pool()
    # Sales sorts by score, so hottest leads come first and the qualification
    # answers are flattened into the row.
    rows = await pool.fetch(
        "SELECT email, name, note, score, qualification, crm_synced, "
        "visitor_id, created_at FROM leads "
        "WHERE site_id = $1 AND created_at > now() - ($2 || ' days')::interval "
        "ORDER BY score DESC, created_at DESC", int(site["id"]), str(days),
    )
    out = []
    for r in rows:
        qual = r["qualification"]
        qual = json.loads(qual) if isinstance(qual, str) else (qual or {})
        out.append({
            "email": r["email"], "name": r["name"], "score": r["score"],
            "qualification": "; ".join(f"{k}: {v}" for k, v in qual.items()),
            "note": r["note"], "crm_synced": r["crm_synced"],
            "visitor_id": r["visitor_id"], "created_at": r["created_at"].isoformat(),
        })
    return _csv(out, ["email", "name", "score", "qualification", "note",
                      "crm_synced", "visitor_id", "created_at"])


@app.delete("/v1/sites/{slug}")
async def delete_site(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], confirm: str = ""
) -> dict:
    """Remove a site and all its data. The slug must be repeated in ?confirm=
    so a stray DELETE can never wipe a knowledge base."""
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    if confirm != slug:
        raise HTTPException(
            status_code=400,
            detail=f"Pass ?confirm={slug} to permanently delete this site and all its data.",
        )
    await store.delete_site(int(site["id"]))
    return {"deleted": slug}


@app.delete("/v1/tenants/{tenant_id}")
async def offboard_tenant(
    tenant_id: int, _: Annotated[AuthContext, Depends(require_admin)], confirm: str = ""
) -> dict:
    """Operator off-boards a client entirely: every site, key, and the tenant
    record. GDPR right-to-erasure in one call."""
    if confirm != str(tenant_id):
        raise HTTPException(
            status_code=400,
            detail=f"Pass ?confirm={tenant_id} to permanently remove this client.",
        )
    sites_removed = await store.delete_tenant(tenant_id)
    return {"deleted_tenant": tenant_id, "sites_removed": sites_removed}


@app.get("/v1/features/catalog")
async def features_catalog() -> dict:
    """The à-la-carte menu + bundles with prices. Public so pricing pages can
    render it."""
    from sitebot import features
    return features.catalog()


def _plan_summary(bundle: str, alacarte: list[str]) -> dict:
    """A client's plan with every feature flagged enabled/locked and priced."""
    from sitebot import features
    eff = features.effective_features(bundle, alacarte)
    bundle_feats = set(features.BUNDLES.get(bundle, {}).get("features", []))
    return {
        "bundle": bundle,
        "bundle_name": features.BUNDLES.get(bundle, {}).get("name", "Custom"),
        "alacarte": [k for k in alacarte if k in features.FEATURES],
        "monthly_cost_cents": features.monthly_cost_cents(bundle, alacarte),
        "features": [
            {
                "key": k, "name": v["name"], "blurb": v["blurb"],
                "price_cents": v["price_cents"],
                "enabled": k in eff,
                "included_in_bundle": k in bundle_feats,
            }
            for k, v in features.FEATURES.items()
        ],
        "bundles": [{"key": k, **v} for k, v in features.BUNDLES.items()],
    }


@app.get("/v1/tenants/me/plan")
async def my_plan(ctx: Annotated[AuthContext, Depends(require_auth)]) -> dict:
    """What this client has enabled and what it costs — the à-la-carte view."""
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant credential.")
    bundle, alacarte = await store.get_entitlements(ctx.tenant_id)
    return _plan_summary(bundle, alacarte)


@app.post("/v1/tenants/me/bundle")
async def choose_bundle(
    body: dict, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    """Pick a pre-made bundle. In production this creates/updates the Stripe
    subscription; here it sets entitlements and returns the new monthly cost."""
    from sitebot import features
    ensure_writer(ctx)
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant credential.")
    bundle = str(body.get("bundle", ""))
    if bundle not in features.BUNDLES:
        raise HTTPException(status_code=400, detail="Unknown bundle.")
    await store.set_bundle(ctx.tenant_id, bundle)
    _, alacarte = await store.get_entitlements(ctx.tenant_id)
    from sitebot import payments
    await payments.audit(f"tenant:{ctx.tenant_id}", "bundle.select", "tenant",
                         str(ctx.tenant_id), {"bundle": bundle})
    return _plan_summary(bundle, alacarte)


@app.post("/v1/tenants/me/features")
async def update_features(
    body: dict, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    """Toggle an à-la-carte feature. Enabling one adds its price to the monthly
    bill immediately; disabling removes it (features already in the bundle stay
    on and free)."""
    from sitebot import features
    ensure_writer(ctx)
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant credential.")
    key = str(body.get("feature", ""))
    if key not in features.FEATURES:
        raise HTTPException(status_code=400, detail="Unknown feature.")
    bundle, alacarte = await store.get_entitlements(ctx.tenant_id)
    current = set(alacarte)
    if body.get("enable"):
        current.add(key)
    else:
        current.discard(key)
    await store.set_alacarte_features(ctx.tenant_id, sorted(current))
    from sitebot import payments
    await payments.audit(
        f"tenant:{ctx.tenant_id}", "feature." + ("enable" if body.get("enable") else "disable"),
        "tenant", str(ctx.tenant_id), {"feature": key},
    )
    return _plan_summary(bundle, sorted(current))


@app.post("/v1/tenants/{tenant_id}/plan")
async def admin_set_plan(
    tenant_id: int, body: dict, _: Annotated[AuthContext, Depends(require_admin)]
) -> dict:
    """Operator sets a client's bundle and à-la-carte features directly."""
    from sitebot import features
    bundle = str(body.get("bundle", ""))
    if bundle and bundle not in features.BUNDLES:
        raise HTTPException(status_code=400, detail="Unknown bundle.")
    alacarte = [k for k in (body.get("features") or []) if k in features.FEATURES]
    await store.set_bundle(tenant_id, bundle)
    await store.set_alacarte_features(tenant_id, alacarte)
    from sitebot import payments
    await payments.audit(
        "admin", "plan.change", "tenant", str(tenant_id),
        {"bundle": bundle, "features": alacarte},
    )
    return _plan_summary(bundle, alacarte)


# =========================== admin billing console ===========================
@app.get("/v1/admin/customers")
async def admin_customers(_: Annotated[AuthContext, Depends(require_admin)]) -> dict:
    """Every client with their plan, monthly value, sites, and usage — the
    operator's customer-management view."""
    from sitebot import features
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT t.id, t.name, t.email, t.plan, t.bundle, t.features, t.billing_status, "
        "t.created_at, count(DISTINCT s.id) AS sites, "
        "count(DISTINCT ue.id) FILTER ("
        "  WHERE ue.created_at >= date_trunc('month', now())) AS msgs_month "
        "FROM tenants t "
        "LEFT JOIN sites s ON s.tenant_id = t.id "
        "LEFT JOIN usage_events ue ON ue.tenant_id = t.id "
        "GROUP BY t.id ORDER BY t.created_at DESC"
    )
    out, mrr = [], 0
    for r in rows:
        feats = r["features"]
        feats = json.loads(feats) if isinstance(feats, str) else (feats or [])
        cost = features.monthly_cost_cents(r["bundle"] or "", feats)
        mrr += cost
        out.append({
            "id": r["id"], "name": r["name"], "email": r["email"],
            "bundle": r["bundle"] or "-", "billing_status": r["billing_status"],
            "monthly_cost_cents": cost, "sites": r["sites"],
            "messages_this_month": r["msgs_month"],
            "created_at": r["created_at"].isoformat(),
        })
    return {"customers": out, "count": len(out), "mrr_cents": mrr}


@app.get("/v1/admin/customers/{tenant_id}")
async def admin_customer_detail(
    tenant_id: int, _: Annotated[AuthContext, Depends(require_admin)]
) -> dict:
    """Everything about one client: plan, sites, payment history, usage."""
    pool = await get_pool()
    t = await pool.fetchrow(
        "SELECT id, name, email, plan, bundle, features, billing_status, created_at "
        "FROM tenants WHERE id = $1", tenant_id
    )
    if t is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    sites = await pool.fetch(
        "SELECT slug, status, pages_indexed, chunks_indexed FROM sites WHERE tenant_id = $1",
        tenant_id,
    )
    pays = await pool.fetch(
        "SELECT id, provider, provider_txn_id, amount_cents, currency, status, "
        "description, created_at FROM payments WHERE tenant_id = $1 "
        "ORDER BY created_at DESC LIMIT 100", tenant_id,
    )
    feats = t["features"]
    feats = json.loads(feats) if isinstance(feats, str) else (feats or [])
    return {
        "tenant": {
            "id": t["id"], "name": t["name"], "email": t["email"],
            "bundle": t["bundle"] or "-", "features": feats,
            "billing_status": t["billing_status"], "created_at": t["created_at"].isoformat(),
        },
        "sites": [dict(s) for s in sites],
        "payments": [
            {**dict(p), "created_at": p["created_at"].isoformat()} for p in pays
        ],
    }


@app.get("/v1/admin/payments")
async def admin_payments(
    _: Annotated[AuthContext, Depends(require_admin)],
    status: str = "", provider: str = "", days: int = 90, limit: int = 500,
) -> dict:
    """The full ledger with filters and a total."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT p.id, p.tenant_id, t.name AS tenant, p.provider, p.provider_txn_id, "
        "p.amount_cents, p.currency, p.status, p.description, p.created_at "
        "FROM payments p LEFT JOIN tenants t ON t.id = p.tenant_id "
        "WHERE p.created_at >= now() - ($1 || ' days')::interval "
        "AND ($2 = '' OR p.status = $2) AND ($3 = '' OR p.provider = $3) "
        "ORDER BY p.created_at DESC LIMIT $4",
        str(int(days)), status, provider, int(limit),
    )
    total = sum(r["amount_cents"] for r in rows if r["status"] == "paid")
    return {
        "payments": [
            {**dict(r), "created_at": r["created_at"].isoformat()} for r in rows
        ],
        "count": len(rows), "paid_total_cents": total,
    }


@app.get("/v1/admin/payments/analytics")
async def admin_payment_analytics(
    _: Annotated[AuthContext, Depends(require_admin)], days: int = 30
) -> dict:
    """Revenue analytics: MRR from active plans, collected revenue, by provider
    and status, and a daily series for charts."""
    from sitebot import features
    pool = await get_pool()
    # MRR from current plans.
    trows = await pool.fetch("SELECT bundle, features FROM tenants")
    mrr = 0
    for r in trows:
        feats = r["features"]
        feats = json.loads(feats) if isinstance(feats, str) else (feats or [])
        mrr += features.monthly_cost_cents(r["bundle"] or "", feats)
    collected = await pool.fetchval(
        "SELECT COALESCE(sum(amount_cents),0) FROM payments "
        "WHERE status = 'paid' AND created_at >= now() - ($1 || ' days')::interval",
        str(int(days)),
    )
    by_provider = await pool.fetch(
        "SELECT provider, count(*) n, "
        "COALESCE(sum(amount_cents) FILTER (WHERE status='paid'),0) paid "
        "FROM payments WHERE created_at >= now() - ($1 || ' days')::interval "
        "GROUP BY provider", str(int(days)),
    )
    by_status = await pool.fetch(
        "SELECT status, count(*) n FROM payments "
        "WHERE created_at >= now() - ($1 || ' days')::interval GROUP BY status",
        str(int(days)),
    )
    daily = await pool.fetch(
        "SELECT date_trunc('day', created_at)::date d, "
        "COALESCE(sum(amount_cents) FILTER (WHERE status='paid'),0) paid "
        "FROM payments WHERE created_at >= now() - ($1 || ' days')::interval "
        "GROUP BY d ORDER BY d", str(int(days)),
    )
    return {
        "mrr_cents": mrr, "collected_cents": int(collected), "window_days": days,
        "by_provider": [dict(r) for r in by_provider],
        "by_status": {r["status"]: r["n"] for r in by_status},
        "daily": [{"date": r["d"].isoformat(), "paid_cents": r["paid"]} for r in daily],
    }


@app.get("/v1/admin/ledger.csv")
async def admin_ledger_csv(
    _: Annotated[AuthContext, Depends(require_admin)], days: int = 365
) -> Response:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT p.id, p.created_at, t.name AS tenant, p.tenant_id, p.provider, "
        "p.provider_txn_id, p.amount_cents, p.currency, p.status, p.description "
        "FROM payments p LEFT JOIN tenants t ON t.id = p.tenant_id "
        "WHERE p.created_at >= now() - ($1 || ' days')::interval ORDER BY p.created_at DESC",
        str(int(days)),
    )
    return _csv(
        [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows],
        ["id", "created_at", "tenant", "tenant_id", "provider", "provider_txn_id",
         "amount_cents", "currency", "status", "description"],
    )


@app.get("/v1/admin/audit")
async def admin_audit(
    _: Annotated[AuthContext, Depends(require_admin)], limit: int = 200
) -> dict:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, actor, action, target_type, target_id, detail, created_at "
        "FROM audit_log ORDER BY created_at DESC LIMIT $1", min(int(limit), 1000)
    )
    return {"events": [
        {**dict(r), "detail": r["detail"] if isinstance(r["detail"], dict)
         else json.loads(r["detail"] or "{}"),
         "created_at": r["created_at"].isoformat()} for r in rows
    ]}


class ManualPayment(BaseModel):
    tenant_id: int
    amount_cents: int
    currency: str = "usd"
    description: str = "Manual entry"
    status: str = Field(default="paid", pattern="^(paid|failed|refunded|created)$")


@app.post("/v1/admin/payments")
async def admin_record_payment(
    body: ManualPayment, ctx: Annotated[AuthContext, Depends(require_admin)]
) -> dict:
    """Record a payment the operator collected out-of-band (bank transfer,
    UPI, cash) so the ledger stays complete."""
    from sitebot import payments
    pid = await payments.record_payment(
        body.tenant_id, "manual", body.amount_cents, status=body.status,
        currency=body.currency, description=body.description,
    )
    return {"payment_id": pid}


@app.post("/v1/admin/payments/{payment_id}/refund")
async def admin_refund(
    payment_id: int, _: Annotated[AuthContext, Depends(require_admin)]
) -> dict:
    from sitebot import payments
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE payments SET status = 'refunded', updated_at = now() "
        "WHERE id = $1 RETURNING tenant_id, amount_cents", payment_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    await payments.audit("admin", "payment.refunded", "payment", str(payment_id),
                         {"amount_cents": row["amount_cents"]})
    return {"refunded": payment_id}


# ------------------------------ razorpay flow ------------------------------
@app.post("/v1/billing/razorpay/order")
async def razorpay_order(ctx: Annotated[AuthContext, Depends(require_auth)]) -> dict:
    """Create a Razorpay order for the caller's current monthly plan total."""
    from sitebot import features, payments
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant credential.")
    bundle, alacarte = await store.get_entitlements(ctx.tenant_id)
    amount = features.monthly_cost_cents(bundle, alacarte)
    cur = "INR" if settings.billing_currency.lower() == "inr" else "USD"
    return await payments.create_razorpay_order(ctx.tenant_id, amount, settings, currency=cur)


@app.post("/v1/billing/razorpay/webhook")
async def razorpay_webhook(request: Request) -> dict:
    from sitebot import payments
    body = await request.body()
    sig = request.headers.get("x-razorpay-signature", "")
    return await payments.handle_razorpay_webhook(body, sig, settings)


@app.get("/v1/tenants/me/export")
async def export_my_data(ctx: Annotated[AuthContext, Depends(require_auth)]) -> Response:
    """GDPR data portability: the tenant's full data as downloadable JSON."""
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant key to export its data.")
    data = await store.export_tenant_data(ctx.tenant_id)
    return Response(
        content=json.dumps(data, indent=1, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sitebot-export.json"'},
    )


@app.post("/v1/tenants/me/rotate-key")
async def rotate_my_key(ctx: Annotated[AuthContext, Depends(require_auth)]) -> dict:
    """Generate a fresh login key for this tenant. The old key stops working
    immediately. Admin/owner only (viewers cannot)."""
    ensure_writer(ctx)
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant key to rotate its key.")
    key, key_hash = generate_tenant_key()
    await store.rotate_tenant_key(ctx.tenant_id, key_hash)
    return {"api_key": key, "note": "Old key is now invalid. Store this one."}


@app.post("/v1/tenants/{tenant_id}/rotate-key")
async def rotate_client_key(
    tenant_id: int, _: Annotated[AuthContext, Depends(require_admin)]
) -> dict:
    """Operator generates a fresh login key for a client tenant (e.g. to hand a
    client their access, or rotate a lost key). Global admin only."""
    key, key_hash = generate_tenant_key()
    ok = await store.rotate_tenant_key(tenant_id, key_hash)
    if not ok:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return {"tenant_id": tenant_id, "api_key": key,
            "note": "Give this to the client. Their old key (if any) is now invalid."}


@app.get("/v1/sites")
async def list_sites(ctx: Annotated[AuthContext, Depends(require_auth)]) -> list[dict]:
    pool = await get_pool()
    if ctx.is_admin:
        rows = await pool.fetch(
            "SELECT slug, start_url, status, pages_indexed, chunks_indexed, "
            "last_indexed_at, tenant_id, public_key FROM sites ORDER BY id"
        )
    else:
        rows = await pool.fetch(
            "SELECT slug, start_url, status, pages_indexed, chunks_indexed, "
            "last_indexed_at, tenant_id, public_key FROM sites WHERE tenant_id = $1 ORDER BY id",
            ctx.tenant_id,
        )
    return [
        {
            **dict(r),
            "last_indexed_at": r["last_indexed_at"].isoformat() if r["last_indexed_at"] else None,
        }
        for r in rows
    ]


@app.post("/v1/sites/{slug}/ingest")
async def trigger_ingest(
    slug: str,
    tasks: BackgroundTasks,
    ctx: Annotated[AuthContext, Depends(require_auth)],
    full: bool = False,
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    if site["status"] in ("crawling", "indexing"):
        raise HTTPException(status_code=409, detail="An ingest is already running.")
    status = await _enqueue_ingest(int(site["id"]), site["start_url"], tasks, full)
    return {"slug": slug, "status": status, "full": full}


@app.get("/v1/sites/{slug}")
async def site_status(slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]) -> dict:
    site = await authorize_site(ctx, slug)
    report = site.get("last_crawl_report")
    keep = (
        "slug", "start_url", "status", "pages_indexed", "chunks_indexed", "last_error",
        "public_key", "display_name", "theme_color", "welcome_message", "avatar_url",
        "widget_position", "allowed_origins", "recrawl_hours", "lead_capture_enabled",
        "lead_prompt", "lead_webhook_url", "handoff_enabled", "handoff_webhook_url",
        "tone", "min_confidence", "hide_branding", "custom_instructions",
        "model_provider", "model_name", "history_turns", "retention_days",
        "proactive_message", "proactive_delay_s", "followups_enabled",
        "widget_language", "digest_webhook_url", "guard_enabled",
        "guard_llm_audit", "guard_refusal_message", "guard_blocks",
        "notify_email", "twilio_from", "digest_channel", "avatar_style", "render_js",
        "crm_provider", "booking_url", "widget_font", "widget_font_url",
        "retrieval_mode", "answer_mode", "fallback_extractive",
    )
    out = {k: site[k] for k in keep if k in site}
    for jkey in (
        "suggested_questions", "canned_answers", "blocked_topics",
        "protected_secrets", "protected_topics", "extra_urls",
        "qualifying_questions",
    ):
        v = site.get(jkey)
        out[jkey] = json.loads(v) if isinstance(v, str) else (v or [])
    out["last_crawl_report"] = json.loads(report) if isinstance(report, str) else (report or {})
    out["last_indexed_at"] = (
        site["last_indexed_at"].isoformat() if site.get("last_indexed_at") else None
    )
    # Channel tokens never leave the server; the dashboard sees status only.
    out["telegram_connected"] = bool(site.get("telegram_bot_token"))
    out["slack_connected"] = bool(site.get("slack_bot_token"))
    out["whatsapp_connected"] = bool(site.get("whatsapp_token"))
    out["sms_connected"] = bool(site.get("twilio_account_sid"))
    out["messenger_connected"] = bool(site.get("messenger_page_token"))
    out["teams_connected"] = bool(site.get("teams_app_id"))
    out["email_configured"] = settings.smtp_configured
    # Guardian values are stored encrypted; owners see plaintext, read-only
    # team members see masks only.
    if ctx.role == "viewer":
        out["protected_secrets"] = ["••••••" for _ in out.get("protected_secrets", [])]
    else:
        from sitebot.crypto import decrypt_secret
        out["protected_secrets"] = [
            decrypt_secret(s) or "" for s in out.get("protected_secrets", [])
        ]
    return out


async def _apply_site_updates(site_id: int, updates: dict[str, Any]) -> list[str]:
    """Apply a validated dict of site settings. Shared by PATCH and onboarding."""
    if not updates:
        return []
    # SSRF guard: the server POSTs to these owner-supplied webhook URLs, so a
    # tenant could otherwise point them at the cloud metadata endpoint or an
    # internal service. Reject non-public hosts, same as AI Actions.
    from sitebot.actions import is_safe_url

    for wk in ("lead_webhook_url", "handoff_webhook_url", "digest_webhook_url"):
        val = updates.get(wk)
        if val and not is_safe_url(val):
            raise HTTPException(
                status_code=400,
                detail=f"{wk} must be a public http(s) endpoint (no private hosts).",
            )
    json_fields = {
        "suggested_questions", "canned_answers", "blocked_topics",
        "protected_secrets", "protected_topics", "extra_urls",
        "qualifying_questions",
    }
    sets: list[str] = []
    values: list[Any] = []
    for i, (col, val) in enumerate(updates.items(), start=2):
        sets.append(f"{col} = ${i}")
        # Client secrets are encrypted at rest; Guardian values per element.
        if col in store.SECRET_COLUMNS and val:
            val = encrypt_secret(val)
        elif col == "protected_secrets" and val:
            val = [encrypt_secret(s) for s in val]
        values.append(json.dumps(val) if col in json_fields else val)
    pool = await get_pool()
    await pool.execute(
        f"UPDATE sites SET {', '.join(sets)}, updated_at = now() WHERE id = $1",
        site_id, *values,
    )
    return sorted(updates)


@app.patch("/v1/sites/{slug}")
async def update_site(
    slug: str, body: UpdateSite, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    updated = await _apply_site_updates(int(site["id"]), body.model_dump(exclude_none=True))
    return {"slug": slug, "updated": updated}


# ------------------------------ analytics API ------------------------------
@app.get("/v1/sites/{slug}/analytics")
async def site_analytics(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], days: int = 30
) -> dict:
    site = await authorize_site(ctx, slug)
    days = max(1, min(days, 365))
    summary = await analytics.site_summary(int(site["id"]), days)
    summary["messages_per_day"] = await analytics.messages_per_day(int(site["id"]), days)
    return summary


@app.get("/v1/sites/{slug}/analytics/top-questions")
async def site_top_questions(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], days: int = 30
) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await analytics.top_questions(int(site["id"]), max(1, min(days, 365)))


@app.get("/v1/sites/{slug}/analytics/unanswered")
async def site_unanswered(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], days: int = 30
) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await analytics.unanswered_questions(int(site["id"]), max(1, min(days, 365)))


@app.get("/v1/sites/{slug}/conversations")
async def site_conversations(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await analytics.recent_conversations(int(site["id"]))


@app.get("/v1/sites/{slug}/conversations/{conversation_id}")
async def site_conversation(
    slug: str, conversation_id: int, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await analytics.conversation_transcript(int(site["id"]), conversation_id)


@app.get("/v1/sites/{slug}/leads")
async def site_leads(slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await analytics.list_leads(int(site["id"]))


@app.get("/v1/sites/{slug}/handoffs")
async def site_handoffs(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await analytics.list_handoffs(int(site["id"]))


# --------------------------- knowledge sources API ---------------------------
@app.post("/v1/sites/{slug}/sources")
async def create_source(
    slug: str, body: SourceCreate, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    if body.kind == "qa":
        if not body.question.strip() or not body.answer.strip():
            raise HTTPException(status_code=400, detail="Q&A sources need question and answer.")
        text = sources_mod.qa_to_text(body.question, body.answer)
        title = body.title or body.question.strip()[:120]
    else:
        text = body.text
        title = body.title or "Text snippet"
    try:
        return await sources_mod.index_source(int(site["id"]), body.kind, title, text, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/sites/{slug}/sources/upload")
async def upload_source(
    slug: str,
    ctx: Annotated[AuthContext, Depends(require_auth)],
    file: Annotated[UploadFile, File()],
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    data = await file.read()
    if len(data) > sources_mod.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20 MB upload limit.")
    try:
        text = sources_mod.extract_text(file.filename or "upload", data)
        return await sources_mod.index_source(
            int(site["id"]), "file", file.filename or "upload", text, settings
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/sites/{slug}/sources")
async def list_sources(slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await store.list_sources(int(site["id"]))


@app.delete("/v1/sites/{slug}/sources/{source_id}")
async def delete_source(
    slug: str, source_id: int, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    ok = await store.delete_source(int(site["id"]), source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found.")
    await store.invalidate_cache(int(site["id"]))
    return {"deleted": source_id}


@app.get("/v1/sites/{slug}/pages")
async def list_pages(slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]) -> list[dict]:
    site = await authorize_site(ctx, slug)
    return await store.list_indexed_pages(int(site["id"]))


@app.delete("/v1/sites/{slug}/pages")
async def delete_page(
    slug: str, url: str, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    ok = await store.delete_indexed_page(int(site["id"]), url)
    if not ok:
        raise HTTPException(status_code=404, detail="Page not found.")
    await store.invalidate_cache(int(site["id"]))
    return {"deleted": url}


# ------------------------------ playground API ------------------------------
@app.post("/v1/sites/{slug}/playground")
async def playground(
    slug: str, body: PlaygroundRequest, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    """Test chat from the dashboard: admin-authenticated, so it works
    regardless of the site's allowed_origins lockdown."""
    site_row = await authorize_site(ctx, slug)
    site = await store.get_site_by_slug(site_row["slug"])
    assert site is not None
    text_parts: list[str] = []
    srcs: list[dict] = []
    action_used = ""
    conversation_id = body.conversation_id
    async for ev in answer_stream(site, body.message, settings, "playground", conversation_id):
        if ev["event"] == "token":
            text_parts.append(ev["data"])
        elif ev["event"] == "sources":
            srcs = ev["data"]
        elif ev["event"] == "action":
            action_used = ev["data"]["name"]
        elif ev["event"] == "done":
            conversation_id = ev["data"]["conversation_id"]
    return {
        "answer": "".join(text_parts), "sources": srcs,
        "conversation_id": conversation_id, "action": action_used,
    }


# -------------------------------- export API --------------------------------
@app.get("/v1/sites/{slug}/export/conversations")
async def export_conversations(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)], format: str = "json"
) -> Response:
    site = await authorize_site(ctx, slug)
    rows = await store.export_conversations(int(site["id"]))
    if format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "conversation_id", "visitor_id", "role", "content", "feedback", "created_at",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{slug}-conversations.csv"'},
        )
    return JSONResponse(
        rows,
        headers={"Content-Disposition": f'attachment; filename="{slug}-conversations.json"'},
    )


# ----------------------------- live agent inbox -----------------------------
@app.post("/v1/sites/{slug}/conversations/{conversation_id}/reply")
async def agent_reply(
    slug: str, conversation_id: int, body: ReplyRequest,
    ctx: Annotated[AuthContext, Depends(require_auth)],
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")
    message_id = await store.add_agent_message(int(site["id"]), conversation_id, body.message)
    if message_id is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"ok": True, "message_id": message_id}


@app.get("/v1/conversations/{conversation_id}/updates")
async def conversation_updates(
    conversation_id: int, key: str, request: Request, after: int = 0
) -> dict:
    """Public: the widget polls this for live agent replies."""
    site = await get_site_by_public_key(key)
    if site is None:
        raise HTTPException(status_code=401, detail="Invalid public key.")
    _check_origin(site, request)
    messages = await store.agent_messages_after(site.id, conversation_id, after)
    return {"messages": messages}


# ------------------------------- channels API -------------------------------
@app.post("/v1/sites/{slug}/channels/telegram")
async def connect_telegram(
    slug: str, body: TelegramSetup, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    require_feature(ctx, "channels")
    site = await authorize_site(ctx, slug)
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET telegram_bot_token = $2, updated_at = now() WHERE id = $1",
        int(site["id"]), encrypt_secret(body.bot_token.strip()),
    )
    webhook_url = ""
    result: dict = {}
    if settings.public_base_url:
        webhook_url = (
            settings.public_base_url.rstrip("/")
            + "/v1/channels/telegram/" + site["public_key"]
        )
        result = await channels.set_telegram_webhook(body.bot_token.strip(), webhook_url)
    else:
        webhook_url = "<PUBLIC_BASE_URL>/v1/channels/telegram/" + site["public_key"]
    return {
        "connected": True,
        "webhook_url": webhook_url,
        "telegram_response": result,
        "note": "" if settings.public_base_url else
                "Set PUBLIC_BASE_URL (public HTTPS) so SiteBot can register the webhook itself.",
    }


@app.delete("/v1/sites/{slug}/channels/telegram")
async def disconnect_telegram(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET telegram_bot_token = '', updated_at = now() WHERE id = $1",
        int(site["id"]),
    )
    return {"connected": False}


@app.post("/v1/channels/telegram/{public_key}")
async def telegram_webhook(public_key: str, request: Request, tasks: BackgroundTasks) -> dict:
    site = await get_site_by_public_key(public_key)
    if site is None or not site.telegram_bot_token:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if secret != channels.telegram_secret(site.telegram_bot_token):
        raise HTTPException(status_code=403, detail="Bad webhook secret.")
    update = await request.json()
    # Telegram expects a fast 200; the answer is generated in the background.
    tasks.add_task(channels.handle_telegram_update, site, update, settings)
    return {"ok": True}


@app.post("/v1/channels/slack/{public_key}")
async def slack_webhook(public_key: str, request: Request, tasks: BackgroundTasks) -> Any:
    site = await get_site_by_public_key(public_key)
    if site is None or not site.slack_signing_secret:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    body = await request.body()
    if not channels.verify_slack_signature(
        site.slack_signing_secret,
        request.headers.get("x-slack-request-timestamp", ""),
        body,
        request.headers.get("x-slack-signature", ""),
    ):
        raise HTTPException(status_code=403, detail="Bad Slack signature.")
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}
    tasks.add_task(channels.handle_slack_event, site, payload, settings)
    return {"ok": True}


# ------------------------------- actions API -------------------------------
@app.get("/v1/sites/{slug}/actions")
async def list_site_actions(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> list[dict]:
    site = await authorize_site(ctx, slug)
    actions = await store.list_actions(int(site["id"]))
    # Static headers hold third-party API keys — mask the VALUES in the API
    # response (keeping key names visible). The real values stay server-side
    # for execution and are never returned to any client, including admins.
    for a in actions:
        a["headers"] = {k: "••••••" for k in (a.get("headers") or {})}
    return actions


@app.post("/v1/sites/{slug}/actions")
async def create_site_action(
    slug: str, body: ActionCreate, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    require_feature(ctx, "ai_actions")
    site = await authorize_site(ctx, slug)
    import re

    from sitebot.actions import is_safe_url

    if body.kind == "http":
        # Substitute {param} placeholders before the SSRF check so templated
        # URLs validate on their real host.
        probe_url = re.sub(r"\{[a-zA-Z0-9_]+\}", "x", body.url)
        if not is_safe_url(probe_url):
            raise HTTPException(
                status_code=400,
                detail="Action URL must be a public http(s) endpoint (no private hosts).",
            )
    existing = await store.list_actions(int(site["id"]))
    if len(existing) >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 actions per site.")
    try:
        action_id = await store.create_action(
            int(site["id"]), body.name, body.description, body.kind,
            body.method, body.url, body.headers, body.params,
        )
    except Exception as exc:  # unique violation on name
        raise HTTPException(status_code=409, detail=f"Action already exists: {body.name}") from exc
    return {"id": action_id, "name": body.name}


@app.patch("/v1/sites/{slug}/actions/{action_id}")
async def toggle_site_action(
    slug: str, action_id: int, body: ActionToggle,
    ctx: Annotated[AuthContext, Depends(require_auth)],
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    ok = await store.set_action_enabled(int(site["id"]), action_id, body.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Action not found.")
    return {"id": action_id, "enabled": body.enabled}


@app.delete("/v1/sites/{slug}/actions/{action_id}")
async def delete_site_action(
    slug: str, action_id: int, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    ok = await store.delete_action(int(site["id"]), action_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Action not found.")
    return {"deleted": action_id}


# ------------------------------ whatsapp channel ------------------------------
@app.post("/v1/sites/{slug}/channels/whatsapp")
async def connect_whatsapp(
    slug: str, body: WhatsAppSetup, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    require_feature(ctx, "channels")
    site = await authorize_site(ctx, slug)
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET whatsapp_token = $2, whatsapp_phone_id = $3, "
        "whatsapp_verify_token = $4, whatsapp_app_secret = $5, updated_at = now() "
        "WHERE id = $1",
        int(site["id"]), encrypt_secret(body.token.strip()), body.phone_id.strip(),
        body.verify_token.strip(), encrypt_secret(body.app_secret.strip()),
    )
    base = settings.public_base_url.rstrip("/") if settings.public_base_url else "<PUBLIC_BASE_URL>"
    return {
        "connected": True,
        "webhook_url": f"{base}/v1/channels/whatsapp/{site['public_key']}",
        "note": "Register this callback URL and your verify token in the Meta app dashboard.",
    }


@app.delete("/v1/sites/{slug}/channels/whatsapp")
async def disconnect_whatsapp(
    slug: str, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    site = await authorize_site(ctx, slug)
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET whatsapp_token = '', whatsapp_phone_id = '', "
        "whatsapp_verify_token = '', whatsapp_app_secret = '', updated_at = now() "
        "WHERE id = $1",
        int(site["id"]),
    )
    return {"connected": False}


@app.get("/v1/channels/whatsapp/{public_key}")
async def whatsapp_verify(public_key: str, request: Request) -> Response:
    """Meta's webhook verification handshake."""
    site = await get_site_by_public_key(public_key)
    params = request.query_params
    if (
        site is not None
        and site.whatsapp_verify_token
        and params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == site.whatsapp_verify_token
    ):
        return Response(params.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed.")


@app.post("/v1/channels/whatsapp/{public_key}")
async def whatsapp_webhook(public_key: str, request: Request, tasks: BackgroundTasks) -> dict:
    site = await get_site_by_public_key(public_key)
    if site is None or not site.whatsapp_token:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    body = await request.body()
    if not channels.verify_whatsapp_signature(
        site.whatsapp_app_secret, body, request.headers.get("x-hub-signature-256", "")
    ):
        raise HTTPException(status_code=403, detail="Bad signature.")
    tasks.add_task(channels.handle_whatsapp_payload, site, json.loads(body), settings)
    return {"ok": True}


# ------------------------- SMS / Messenger / Teams -------------------------
@app.post("/v1/channels/sms/{public_key}")
async def sms_webhook(public_key: str, request: Request, tasks: BackgroundTasks) -> Response:
    site = await get_site_by_public_key(public_key)
    if site is None or not site.twilio_account_sid:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    body = await request.body()
    form = {k: v for k, v in (await request.form()).items()}
    url = f"{settings.public_base_url.rstrip('/')}/v1/channels/sms/{public_key}"
    if not channels.verify_twilio_signature(
        site.twilio_auth_token, url,
        {k: str(v) for k, v in form.items()},
        request.headers.get("x-twilio-signature", ""),
    ):
        raise HTTPException(status_code=403, detail="Bad Twilio signature.")
    tasks.add_task(channels.handle_twilio_sms, site, body, settings)
    # Empty TwiML: we reply out-of-band via the Messages API.
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )


@app.post("/v1/channels/voice/{public_key}")
async def voice_webhook(public_key: str, request: Request) -> Response:
    """Phone Voice AI: point a Twilio number's Voice webhook here. Each turn
    Twilio POSTs the caller's transcribed speech; we answer from the site's
    knowledge base and TwiML speaks it back, then listens again."""
    site = await get_site_by_public_key(public_key)
    if site is None or not site.twilio_account_sid:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    if not await store.tenant_has_feature(site.tenant_id, "voice"):
        raise HTTPException(status_code=402, detail="Phone Voice AI is not on this plan.")
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = f"{settings.public_base_url.rstrip('/')}/v1/channels/voice/{public_key}"
    if not channels.verify_twilio_signature(
        site.twilio_auth_token, url, form,
        request.headers.get("x-twilio-signature", ""),
    ):
        raise HTTPException(status_code=403, detail="Bad Twilio signature.")
    twiml = await channels.handle_voice_turn(site, form, settings, url)
    return Response(twiml, media_type="application/xml")


@app.get("/v1/channels/messenger/{public_key}")
async def messenger_verify(public_key: str, request: Request) -> Response:
    site = await get_site_by_public_key(public_key)
    p = request.query_params
    if (
        site is not None and site.messenger_verify_token
        and p.get("hub.mode") == "subscribe"
        and p.get("hub.verify_token") == site.messenger_verify_token
    ):
        return Response(p.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed.")


@app.post("/v1/channels/messenger/{public_key}")
async def messenger_webhook(public_key: str, request: Request, tasks: BackgroundTasks) -> dict:
    site = await get_site_by_public_key(public_key)
    if site is None or not site.messenger_page_token:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    body = await request.body()
    if not channels.verify_whatsapp_signature(
        site.messenger_app_secret, body, request.headers.get("x-hub-signature-256", "")
    ):
        raise HTTPException(status_code=403, detail="Bad signature.")
    tasks.add_task(channels.handle_messenger_payload, site, json.loads(body), settings)
    return {"ok": True}


@app.post("/v1/channels/teams/{public_key}")
async def teams_webhook(public_key: str, request: Request, tasks: BackgroundTasks) -> dict:
    site = await get_site_by_public_key(public_key)
    if site is None or not site.teams_app_id:
        raise HTTPException(status_code=404, detail="Unknown channel.")
    # Validate the Bot Framework JWT: signature against Microsoft's published
    # signing keys, plus issuer, audience (our bot app id), and expiry.
    try:
        valid = await channels.verify_teams_jwt(
            site.teams_app_id, request.headers.get("authorization", "")
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid bot token.")
    activity = await request.json()
    # Bind the reply to the JWT-verified serviceUrl only if the activity's
    # serviceUrl is a Bot Framework host (defense against a spoofed reply target).
    tasks.add_task(channels.handle_teams_activity, site, activity, settings)
    return {"ok": True}


# ------------------------------- team keys API -------------------------------
@app.post("/v1/tenants/me/keys")
async def create_team_key(
    body: TeamKeyCreate, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant key to manage team keys.")
    key, key_hash = generate_tenant_key()
    key_id = await store.create_tenant_key(ctx.tenant_id, body.name, key_hash, body.role)
    return {"id": key_id, "name": body.name, "role": body.role, "api_key": key,
            "note": "Store this key now; it is not shown again."}


@app.get("/v1/tenants/me/keys")
async def list_team_keys(ctx: Annotated[AuthContext, Depends(require_auth)]) -> list[dict]:
    if ctx.tenant_id is None:
        return []
    return await store.list_tenant_keys(ctx.tenant_id)


@app.delete("/v1/tenants/me/keys/{key_id}")
async def revoke_team_key(
    key_id: int, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    ensure_writer(ctx)
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant key to manage team keys.")
    ok = await store.revoke_tenant_key(ctx.tenant_id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found.")
    return {"revoked": key_id}


# ------------------------------- billing API -------------------------------
@app.post("/v1/billing/checkout")
async def billing_checkout(
    body: CheckoutRequest, ctx: Annotated[AuthContext, Depends(require_auth)]
) -> dict:
    if ctx.tenant_id is None:
        raise HTTPException(status_code=400, detail="Use a tenant key to start checkout.")
    url = await billing.create_checkout_session(
        ctx.tenant_id, body.price_id, body.success_url, body.cancel_url, settings
    )
    return {"checkout_url": url}


@app.post("/v1/billing/webhook")
async def billing_webhook(request: Request) -> dict:
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    return await billing.handle_webhook(payload, signature, settings)


# ------------------------------- public API -------------------------------
@app.get("/v1/widget/config")
async def widget_config(key: str) -> dict:
    site = await get_site_by_public_key(key)
    if site is None:
        raise HTTPException(status_code=401, detail="Invalid public key.")
    return {
        "slug": site.slug,
        "display_name": site.display_name,
        "theme_color": site.theme_color,
        "welcome_message": site.welcome_message,
        "status": site.status,
        "avatar_url": site.avatar_url,
        "position": site.widget_position,
        "suggested_questions": site.suggested_questions,
        "lead_capture_enabled": site.lead_capture_enabled,
        "lead_prompt": site.lead_prompt,
        "booking_url": site.booking_url,
        "qualifying_questions": site.qualifying_questions,
        "handoff_enabled": site.handoff_enabled,
        "hide_branding": site.hide_branding,
        "language": site.widget_language,
        "avatar_style": site.avatar_style,
        "widget_font": site.widget_font,
        "widget_font_url": site.widget_font_url,
        "proactive_message": site.proactive_message,
        "proactive_delay_s": site.proactive_delay_s,
        "last_indexed_at": site.last_indexed_at.isoformat() if site.last_indexed_at else None,
    }


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _chat_preflight(body: ChatRequest, request: Request) -> SiteRow:
    site = await get_site_by_public_key(body.key)
    if site is None:
        raise HTTPException(status_code=401, detail="Invalid public key.")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")
    _check_origin(site, request)
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(f"{body.key}:{client_ip}", settings)
    await enforce_monthly_quota(site.tenant_id, site.plan, settings)
    return site


@app.post("/v1/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    site = await _chat_preflight(body, request)

    async def event_source():  # type: ignore[no-untyped-def]
        try:
            async for ev in answer_stream(
                site, body.message, settings, body.visitor_id, body.conversation_id
            ):
                yield _sse(ev["event"], ev["data"])
        except Exception:  # noqa: BLE001
            # Log the real cause server-side; never leak internal exception text
            # (DB/provider errors, keys in messages) to the public visitor.
            log.exception("chat stream failed for site %s", site.slug)
            yield _sse("error", {"message": "The assistant hit an error. Please try again."})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/chat")
async def chat(body: ChatRequest, request: Request) -> JSONResponse:
    """Non-streaming variant that returns the full answer and sources."""
    site = await _chat_preflight(body, request)
    text_parts: list[str] = []
    sources: list[dict] = []
    conversation_id = body.conversation_id
    try:
        async for ev in answer_stream(
            site, body.message, settings, body.visitor_id, body.conversation_id
        ):
            if ev["event"] == "token":
                text_parts.append(ev["data"])
            elif ev["event"] == "sources":
                sources = ev["data"]
            elif ev["event"] == "done":
                conversation_id = ev["data"]["conversation_id"]
    except Exception:  # noqa: BLE001
        # Provider outage / quota exhaustion is retryable, so tell the widget
        # that (503 + Retry-After) instead of a dead-end 500. Real cause goes
        # to the server log only.
        log.exception("chat failed for site %s", site.slug)
        return JSONResponse(
            {"detail": "The assistant is temporarily unavailable. Please try again shortly."},
            status_code=503,
            headers={"Retry-After": "30"},
        )
    return JSONResponse(
        {"answer": "".join(text_parts), "sources": sources, "conversation_id": conversation_id}
    )


@app.post("/v1/feedback")
async def feedback(body: FeedbackRequest, request: Request) -> dict:
    site = await get_site_by_public_key(body.key)
    if site is None:
        raise HTTPException(status_code=401, detail="Invalid public key.")
    _check_origin(site, request)
    if body.value not in (1, -1):
        raise HTTPException(status_code=400, detail="value must be 1 or -1.")
    ok = await store.record_feedback(body.conversation_id, body.message_index, body.value)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found.")
    return {"ok": True}


@app.post("/v1/leads")
async def create_lead(body: LeadRequest, request: Request, tasks: BackgroundTasks) -> dict:
    site = await get_site_by_public_key(body.key)
    if site is None:
        raise HTTPException(status_code=401, detail="Invalid public key.")
    _check_origin(site, request)
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(f"lead:{body.key}:{client_ip}", settings)
    lead_id = await store.create_lead(
        site.id, body.conversation_id, str(body.email), body.name, body.note, body.visitor_id
    )
    # Qualification + a simple transparent score: answered questions and a
    # message each add signal. Sales teams sort by this in the dashboard/CRM.
    qual = {k: v for k, v in (body.qualification or {}).items() if v.strip()}
    if qual or body.note:
        score = min(100, 40 + 15 * len(qual) + (10 if body.note.strip() else 0))
    else:
        score = 20
    pool = await get_pool()
    await pool.execute(
        "UPDATE leads SET qualification = $2, score = $3 WHERE id = $1",
        lead_id, json.dumps(qual), score,
    )
    lead_payload = {
        "lead_id": lead_id, "site": site.slug, "email": str(body.email),
        "name": body.name, "note": body.note, "qualification": qual, "score": score,
    }
    # Native CRM sync runs in the background; failures never block the visitor.
    # Only when the client's plan includes the CRM feature.
    if site.crm_provider and await store.tenant_has_feature(site.tenant_id, "crm"):
        from sitebot import crm
        tasks.add_task(
            crm.push_lead, lead_id, site.crm_provider, site.crm_api_key,
            site.lead_webhook_url, lead_payload,
        )
    if site.lead_webhook_url and site.crm_provider != "webhook":
        tasks.add_task(webhooks.deliver, site.lead_webhook_url, "lead.created", lead_payload)
    if site.notify_email and settings.smtp_configured:
        subject, text = email_out.lead_email(site.slug, str(body.email), body.name, body.note)
        tasks.add_task(email_out.send_email, settings, site.notify_email, subject, text)
    return {"ok": True, "lead_id": lead_id}


@app.post("/v1/handoff")
async def request_handoff(body: HandoffRequest, request: Request, tasks: BackgroundTasks) -> dict:
    site = await get_site_by_public_key(body.key)
    if site is None:
        raise HTTPException(status_code=401, detail="Invalid public key.")
    if not site.handoff_enabled:
        raise HTTPException(status_code=400, detail="Handoff is not enabled for this site.")
    _check_origin(site, request)
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(f"handoff:{body.key}:{client_ip}", settings)
    handoff_id = await store.create_handoff(
        site.id, body.conversation_id, body.email, body.message, body.visitor_id
    )
    if site.handoff_webhook_url:
        tasks.add_task(
            webhooks.deliver, site.handoff_webhook_url, "handoff.requested",
            {"handoff_id": handoff_id, "site": site.slug, "email": body.email,
             "message": body.message, "conversation_id": body.conversation_id},
        )
    if site.notify_email and settings.smtp_configured:
        subject, text = email_out.handoff_email(site.slug, body.email, body.message)
        tasks.add_task(email_out.send_email, settings, site.notify_email, subject, text)
    return {"ok": True, "handoff_id": handoff_id}


# ----------------------------- static assets ------------------------------
@app.get("/dashboard")
async def dashboard() -> FileResponse:
    return FileResponse(_STATIC_DIR / "dashboard.html", media_type="text/html")


@app.get("/onboarding")
async def onboarding_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "onboarding.html", media_type="text/html")


@app.get("/widget.js")
async def widget_js() -> FileResponse:
    return FileResponse(
        _WIDGET_DIR / "widget.js",
        media_type="application/javascript; charset=utf-8",
        # Short TTL: widget fixes must reach customer sites without asking
        # every client to cache-bust their embed snippet.
        headers={"Cache-Control": "public, max-age=300"},
    )


# Pre-made agent avatars (regional personas selectable during onboarding).
# The strict filename pattern doubles as the path-traversal guard.
_AGENT_NAME_RE = re.compile(r"^[a-z_]{1,40}\.webp$")


@app.get("/static/agents/{filename}")
async def agent_avatar(filename: str) -> FileResponse:
    if not _AGENT_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=404, detail="Not found.")
    path = _STATIC_DIR / "agents" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(
        path, media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


# ------------------------------ live inbox WS ------------------------------
from fastapi import WebSocket  # noqa: E402


@app.websocket("/v1/ws/sites/{slug}/inbox")
async def inbox_ws(ws: WebSocket, slug: str, key: str = "") -> None:
    """Pushes new conversation messages to the dashboard as they happen.
    Auth: the same tenant/admin/session credential, passed as ?key=."""
    import asyncio as _aio

    from fastapi import WebSocketDisconnect
    try:
        ctx = await require_auth(key)
        site = await authorize_site(ctx, slug)
    except HTTPException:
        await ws.close(code=4401)
        return
    await ws.accept()
    pool = await get_pool()
    watermark = await pool.fetchval(
        "SELECT COALESCE(max(m.id), 0) FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id WHERE c.site_id = $1",
        int(site["id"]),
    )
    try:
        while True:
            await _aio.sleep(2.0)
            rows = await pool.fetch(
                "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at "
                "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.site_id = $1 AND m.id > $2 ORDER BY m.id LIMIT 50",
                int(site["id"]), int(watermark),
            )
            for r in rows:
                watermark = max(watermark, r["id"])
                await ws.send_json({
                    "conversation_id": r["conversation_id"], "role": r["role"],
                    "content": r["content"][:500], "at": r["created_at"].isoformat(),
                })
    except (WebSocketDisconnect, RuntimeError):
        return


# --------------------------------- probes ---------------------------------
@app.middleware("http")
async def _measure(request: Request, call_next):  # type: ignore[no-untyped-def]
    import time as _t
    start = _t.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", request.url.path)
    from sitebot import metrics as _metrics
    _metrics.observe(request.method, route, response.status_code, _t.perf_counter() - start)
    return response


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    from sitebot import metrics as _metrics
    return Response(content=_metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    ready = await check_ready()
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)
