"""Database pool, schema bootstrap, and a plain-SQL migration runner."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from sitebot.config import get_settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

# Repo layout (editable install) or the container WORKDIR (pip install .).
_SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
if not _SQL_DIR.exists():
    _SQL_DIR = Path.cwd() / "sql"
_SCHEMA_PATH = _SQL_DIR / "schema.sql"
_MIGRATIONS_DIR = _SQL_DIR / "migrations"


async def _init_connection(conn: asyncpg.Connection) -> None:
    try:
        await register_vector(conn)
    except ValueError:
        # Fresh database: the extension does not exist yet, so the type
        # cannot be introspected. Create it and retry.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await register_vector(conn)


async def get_pool() -> asyncpg.Pool:
    """Return a lazily created connection pool."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            # Recycle idle connections so a long-lived deployment doesn't pin
            # stale server-side state; 5 min matches typical LB idle timeouts.
            max_inactive_connection_lifetime=300.0,
            command_timeout=60.0,
            init=_init_connection,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema() -> None:
    """Create baseline tables, then apply any pending migrations.

    The vector dimension in schema.sql is written for the default embedding
    model (1536); it is substituted with EMBED_DIM so the schema and the
    configured embedding model can never drift apart on a fresh database.
    """
    settings = get_settings()
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    sql = sql.replace("vector(1536)", f"vector({settings.embed_dim})")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql)
    await run_migrations()


async def run_migrations() -> list[str]:
    """Apply SQL files in sql/migrations in filename order, exactly once each.

    Applied filenames are recorded in schema_migrations. Each migration runs in
    its own transaction so a failure leaves earlier migrations applied.
    """
    pool = await get_pool()
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {
            r["filename"] for r in await conn.fetch("SELECT filename FROM schema_migrations")
        }
        if not _MIGRATIONS_DIR.exists():
            return applied
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
                )
            log.info("migration applied: %s", path.name)
            applied.append(path.name)
    return applied


async def check_ready() -> bool:
    """Cheap readiness check used by /readyz."""
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
