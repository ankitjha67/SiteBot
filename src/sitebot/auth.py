"""Authentication: global admin key plus per-tenant scoped API keys.

The global ADMIN_API_KEY is the superuser. Each tenant additionally gets its
own key ("tk_..."); only its sha256 hash is stored. Tenant keys can manage the
tenant's own sites and nothing else.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException

from sitebot.config import get_settings
from sitebot.db import get_pool


@dataclass(slots=True)
class AuthContext:
    is_admin: bool
    tenant_id: int | None  # None for the global admin
    role: str = "admin"    # admin | viewer (team keys can be read-only)
    features: frozenset[str] = frozenset()  # tenant's effective feature set

    def can_access_tenant(self, tenant_id: int) -> bool:
        return self.is_admin or self.tenant_id == tenant_id

    def has_feature(self, key: str) -> bool:
        return self.is_admin or key in self.features


def require_feature(ctx: AuthContext, key: str) -> None:
    """Gate a paid feature. 402 Payment Required when the client hasn't
    subscribed to it, so the dashboard can prompt an upgrade."""
    from sitebot.features import FEATURES

    if not ctx.has_feature(key):
        name = FEATURES.get(key, {}).get("name", key)
        raise HTTPException(
            status_code=402,
            detail=f"'{name}' is not enabled on this plan. Add it from Plan & Features.",
        )


def ensure_writer(ctx: AuthContext) -> None:
    """Mutating endpoints reject read-only team keys."""
    if ctx.role == "viewer":
        raise HTTPException(status_code=403, detail="This key is read-only.")


def generate_tenant_key() -> tuple[str, str]:
    """Return (plaintext_key, sha256_hash). The plaintext is shown exactly once."""
    key = "tk_" + secrets.token_urlsafe(24)
    return key, hash_key(key)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ------------------------- user accounts (email login) -------------------------
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
SESSION_TTL_S = 14 * 24 * 3600  # two weeks


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except (ValueError, TypeError):
        return False


async def create_session(user_id: int) -> str:
    """Mint a session token ('st_...'); only its hash is stored."""
    token = "st_" + secrets.token_urlsafe(32)
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO user_sessions (token_hash, user_id, expires_at) "
        "VALUES ($1, $2, now() + ($3 || ' seconds')::interval)",
        hash_key(token), user_id, str(SESSION_TTL_S),
    )
    return token


async def _session_context(token: str) -> AuthContext | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT u.tenant_id, u.role FROM user_sessions s "
        "JOIN tenant_users u ON u.id = s.user_id "
        "WHERE s.token_hash = $1 AND s.expires_at > now()",
        hash_key(token),
    )
    if row is None:
        return None
    from sitebot import store

    feats = await store.effective_features(int(row["tenant_id"]))
    return AuthContext(
        is_admin=False, tenant_id=int(row["tenant_id"]), role=row["role"], features=feats
    )


async def require_auth(x_api_key: Annotated[str, Header()] = "") -> AuthContext:
    """Accept the global admin key or a tenant key. 401 otherwise."""
    settings = get_settings()
    if x_api_key and secrets.compare_digest(x_api_key, settings.admin_api_key):
        return AuthContext(is_admin=True, tenant_id=None)
    from sitebot import store

    if x_api_key.startswith("tk_"):
        key_hash = hash_key(x_api_key)
        pool = await get_pool()
        tenant_id = await pool.fetchval(
            "SELECT id FROM tenants WHERE api_key_hash = $1", key_hash
        )
        if tenant_id is not None:
            feats = await store.effective_features(int(tenant_id))
            return AuthContext(
                is_admin=False, tenant_id=int(tenant_id), role="admin", features=feats
            )
        # Team member keys carry a role and can be revoked individually.
        member = await store.find_tenant_key(key_hash)
        if member is not None:
            feats = await store.effective_features(member["tenant_id"])
            return AuthContext(
                is_admin=False, tenant_id=member["tenant_id"],
                role=member["role"], features=feats,
            )
    if x_api_key.startswith("st_"):
        # Browser session from an email+password login.
        ctx = await _session_context(x_api_key)
        if ctx is not None:
            return ctx
    raise HTTPException(status_code=401, detail="Invalid API key.")


async def require_admin(x_api_key: Annotated[str, Header()] = "") -> AuthContext:
    """Global admin only (tenant creation, cross-tenant operations)."""
    ctx = await require_auth(x_api_key)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="Requires the global admin key.")
    return ctx


async def authorize_site(ctx: AuthContext, slug: str) -> dict:
    """Return the site row if the caller may manage it, else 403/404."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM sites WHERE slug = $1", slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Site not found.")
    if not ctx.can_access_tenant(int(row["tenant_id"])):
        raise HTTPException(status_code=403, detail="Not your site.")
    return dict(row)
