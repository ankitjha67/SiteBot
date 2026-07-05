"""Seed a small fixture site for the CI eval gate.

Indexes fixed page content through the real chunking + embedding pipeline
(no crawling, no network beyond the one-time embedding model download), so
`sitebot eval ci-fixture evals/ci-fixture.json` exercises the same retrieval
stack production uses. Idempotent: re-running replaces the fixture content.
"""

from __future__ import annotations

import asyncio
import secrets

from sitebot import store
from sitebot.auth import generate_tenant_key
from sitebot.config import get_settings
from sitebot.crawler import Page
from sitebot.db import apply_schema, close_pool, get_pool
from sitebot.embeddings import embed_texts
from sitebot.ingest import chunk_page, content_hash

PAGES = [
    Page(
        url="https://ci.fixture/returns",
        title="Returns Policy",
        text=(
            "Customers may return any unused item within 30 days of delivery "
            "for a full refund. Refunds are issued to the original payment "
            "method within 5 business days of us receiving the item. "
            "Sale items marked final sale cannot be returned."
        ),
    ),
    Page(
        url="https://ci.fixture/support",
        title="Support Hours",
        text=(
            "Our support team is available Monday to Friday from 9am to 6pm "
            "Central European Time. Weekend enquiries are answered on the "
            "next business day. Enterprise customers get a dedicated line "
            "with a 4 hour response guarantee."
        ),
    ),
    Page(
        url="https://ci.fixture/pricing",
        title="Pricing",
        text=(
            "The starter plan costs 29 euros per month and includes up to "
            "three projects. The business plan costs 99 euros per month with "
            "unlimited projects and priority support. Annual billing saves "
            "two months on either plan."
        ),
    ),
]


async def main() -> None:
    settings = get_settings()
    await apply_schema()
    pool = await get_pool()

    site_id = await pool.fetchval("SELECT id FROM sites WHERE slug = 'ci-fixture'")
    if site_id is None:
        _, key_hash = generate_tenant_key()
        tenant_id = await store.create_tenant("ci-fixture", "", "trial", key_hash)
        site_id = await pool.fetchval(
            "INSERT INTO sites (tenant_id, slug, start_url, public_key) "
            "VALUES ($1, 'ci-fixture', 'https://ci.fixture', $2) RETURNING id",
            tenant_id, "pk_ci_" + secrets.token_urlsafe(8),
        )

    chunks = [c for page in PAGES for c in chunk_page(page, settings)]
    vectors = await embed_texts([c.content for c in chunks], settings)
    rows = [
        (c.url, c.title, c.content, c.token_count, v)
        for c, v in zip(chunks, vectors, strict=True)
    ]
    urls = sorted({p.url for p in PAGES})
    await store.apply_incremental_index(
        int(site_id), rows=rows, changed_urls=urls, removed_urls=[],
        page_hashes={p.url: (content_hash(p.text), p.title) for p in PAGES},
        seen_urls=urls, full=True,
    )
    await store.finalise_index(int(site_id), len(PAGES), len(rows))
    print(f"ci-fixture indexed: {len(PAGES)} pages, {len(rows)} chunks")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
