"""Integration tests against a real Postgres (pgvector) database.

These exercise the persistence layer end to end: tenant/site lifecycle, the
incremental index diff, vector + trigram search, the answer cache, tenant
isolation, and pool behaviour under concurrent writes.

They run whenever DATABASE_URL points at a reachable database (locally and in
CI, which starts a pgvector service). When no database is reachable the whole
module skips - unit tests stay green offline.

Every row created here uses the itest- prefix and is deleted afterwards, so
running against a development database is safe.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid

import pytest

from sitebot import store
from sitebot.auth import generate_tenant_key
from sitebot.config import get_settings
from sitebot.db import apply_schema, close_pool, get_pool


async def _db_available() -> bool:
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "no database here"
        return False


# The pool is a module global bound to the event loop that created it, and
# pytest-asyncio gives every test its own loop - so the pool must be opened
# and closed inside each test's loop.
@pytest.fixture(autouse=True)
async def _require_db():
    if not await _db_available():
        await close_pool()
        pytest.skip("no reachable DATABASE_URL; skipping integration tests")
    await apply_schema()
    yield
    # Remove everything this test created (identified by the itest- prefix).
    pool = await get_pool()
    site_ids = [
        r["id"] for r in await pool.fetch("SELECT id FROM sites WHERE slug LIKE 'itest-%'")
    ]
    if site_ids:
        await pool.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE site_id = ANY($1::int[]))", site_ids
        )
        for table in ("chunks", "pages", "conversations", "answer_cache", "usage_events"):
            await pool.execute(
                f"DELETE FROM {table} WHERE site_id = ANY($1::int[])", site_ids
            )
        await pool.execute("DELETE FROM sites WHERE id = ANY($1::int[])", site_ids)
    await pool.execute("DELETE FROM tenants WHERE name LIKE 'itest-%'")
    await close_pool()


def _vec(seed: float) -> list[float]:
    """A deterministic unit-ish vector of the configured dimension."""
    dim = get_settings().embed_dim
    v = [0.001] * dim
    v[int(seed) % dim] = 1.0
    return v


async def _make_site(**site_cols) -> tuple[int, int]:
    """Create an itest tenant + site; returns (tenant_id, site_id)."""
    _, key_hash = generate_tenant_key()
    tenant_id = await store.create_tenant(f"itest-{uuid.uuid4().hex[:8]}", "", "trial", key_hash)
    pool = await get_pool()
    slug = f"itest-{uuid.uuid4().hex[:10]}"
    cols = {
        "start_url": "https://itest.example",
        "public_key": "pk_itest_" + secrets.token_urlsafe(8),
    }
    cols.update(site_cols)
    site_id = await pool.fetchval(
        "INSERT INTO sites (tenant_id, slug, start_url, public_key) "
        "VALUES ($1, $2, $3, $4) RETURNING id",
        tenant_id, slug, cols["start_url"], cols["public_key"],
    )
    return tenant_id, int(site_id)


async def test_tenant_key_rotation_swaps_hash() -> None:
    key, key_hash = generate_tenant_key()
    tenant_id = await store.create_tenant("itest-rotate", "", "trial", key_hash)
    _, new_hash = generate_tenant_key()
    assert await store.rotate_tenant_key(tenant_id, new_hash) is True
    pool = await get_pool()
    stored = await pool.fetchval("SELECT api_key_hash FROM tenants WHERE id = $1", tenant_id)
    assert stored == new_hash != key_hash
    assert await store.rotate_tenant_key(999_999_999, new_hash) is False


async def test_seed_urls_combine_start_and_extra() -> None:
    _, site_id = await _make_site()
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET extra_urls = $2 WHERE id = $1",
        site_id, '["https://docs.itest.example", "https://help.itest.example"]',
    )
    seeds = await store.get_seed_urls(site_id)
    assert seeds == [
        "https://itest.example",
        "https://docs.itest.example",
        "https://help.itest.example",
    ]


async def test_incremental_index_and_hybrid_search_roundtrip() -> None:
    _, site_id = await _make_site()
    url_a, url_b = "https://itest.example/a", "https://itest.example/b"
    rows = [
        (url_a, "Page A", "the grinder warranty lasts three years", 8, _vec(1)),
        (url_b, "Page B", "standard shipping costs five dollars", 7, _vec(2)),
    ]
    await store.apply_incremental_index(
        site_id, rows=rows, changed_urls=[url_a, url_b], removed_urls=[],
        page_hashes={url_a: ("hash-a", "Page A"), url_b: ("hash-b", "Page B")},
        seen_urls=[url_a, url_b],
    )
    assert await store.count_chunks(site_id) == 2

    # Vector search: the query vector aligned with page A must rank it first.
    hits = await store.search_chunks(site_id, _vec(1), top_k=2, min_score=0.0)
    assert hits and hits[0].url == url_a

    # Trigram search finds by exact-ish words.
    kw = await store.keyword_fallback(site_id, "grinder warranty", top_k=3)
    assert any(h.url == url_a for h in kw)

    # Incremental diff: drop page B, change page A.
    rows2 = [(url_a, "Page A", "the grinder warranty lasts two years now", 8, _vec(3))]
    await store.apply_incremental_index(
        site_id, rows=rows2, changed_urls=[url_a], removed_urls=[url_b],
        page_hashes={url_a: ("hash-a2", "Page A")}, seen_urls=[url_a],
    )
    hashes = await store.get_page_hashes(site_id)
    assert hashes == {url_a: "hash-a2"}
    assert await store.count_chunks(site_id) == 1


async def test_search_is_scoped_to_one_site() -> None:
    _, site_1 = await _make_site()
    _, site_2 = await _make_site()
    await store.apply_incremental_index(
        site_1,
        rows=[("https://itest.example/secret", "S", "tenant one private text", 5, _vec(7))],
        changed_urls=["https://itest.example/secret"], removed_urls=[],
        page_hashes={"https://itest.example/secret": ("h", "S")},
        seen_urls=["https://itest.example/secret"],
    )
    # The other site must see nothing, even with the exact matching vector.
    assert await store.search_chunks(site_2, _vec(7), top_k=5, min_score=0.0) == []
    assert await store.keyword_fallback(site_2, "tenant one private", top_k=5) == []


async def test_answer_cache_roundtrip_and_ttl() -> None:
    _, site_id = await _make_site()
    qhash = "h" * 64
    await store.cache_put(site_id, qhash, "cached answer", [{"index": "1", "url": "u"}])
    hit = await store.cache_get(site_id, qhash, ttl_s=3600)
    assert hit is not None and hit["answer"] == "cached answer"
    # An expired TTL must miss even though the row exists.
    assert await store.cache_get(site_id, qhash, ttl_s=0) is None


async def test_delete_site_removes_every_row() -> None:
    tenant_id, site_id = await _make_site()
    await store.apply_incremental_index(
        site_id,
        rows=[("https://itest.example/x", "X", "content here", 3, _vec(4))],
        changed_urls=["https://itest.example/x"], removed_urls=[],
        page_hashes={"https://itest.example/x": ("h", "X")},
        seen_urls=["https://itest.example/x"],
    )
    await store.log_message(site_id, tenant_id, "v1", None, "q", "a", [])
    await store.delete_site(site_id)
    pool = await get_pool()
    for table in ("sites", "chunks", "pages", "conversations"):
        col = "id" if table == "sites" else "site_id"
        n = await pool.fetchval(f"SELECT count(*) FROM {table} WHERE {col} = $1", site_id)
        assert int(n) == 0, table


async def test_export_tenant_data_has_conversations_but_no_secrets() -> None:
    tenant_id, site_id = await _make_site()
    pool = await get_pool()
    await pool.execute(
        "UPDATE sites SET llm_api_key = $2 WHERE id = $1", site_id, "sk-super-secret"
    )
    await store.log_message(site_id, tenant_id, "v1", None, "hello?", "hi!", [])
    data = await store.export_tenant_data(tenant_id)
    assert data["tenant"]["id"] == tenant_id
    site = data["sites"][0]
    assert site["llm_api_key"] is True  # configured -> boolean, never the value
    assert "sk-super-secret" not in json.dumps(data)
    assert site["conversations"][0]["messages"][0]["content"] == "hello?"


async def test_concurrent_message_logging_under_pool_pressure() -> None:
    """50 concurrent writes across the pool must all commit, without errors.
    This is the regression net for pool sizing and connection reuse."""
    tenant_id, site_id = await _make_site()

    async def one(i: int) -> int:
        return await store.log_message(
            site_id, tenant_id, f"visitor-{i}", None,
            f"question {i}", f"answer {i}", [], answered=True, confidence=0.9,
        )

    conv_ids = await asyncio.gather(*(one(i) for i in range(50)))
    assert len(conv_ids) == 50 and all(isinstance(c, int) for c in conv_ids)
    pool = await get_pool()
    n = await pool.fetchval(
        "SELECT count(*) FROM messages WHERE conversation_id IN "
        "(SELECT id FROM conversations WHERE site_id = $1)", site_id
    )
    assert int(n) == 100  # each log_message writes a user + assistant pair
