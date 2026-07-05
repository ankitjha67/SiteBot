"""Ingestion pipeline: crawl -> diff -> chunk -> embed -> store.

Incremental by default: each page's extracted text is hashed; only new or
changed pages are re-chunked and re-embedded, and pages that disappeared from
the site are pruned. Embedding failures are retried per batch and reported in
the site's crawl report rather than failing the whole run.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from sitebot import store
from sitebot.config import Settings
from sitebot.crawler import Page, crawl_many, crawl_site
from sitebot.embeddings import embed_texts

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Chunk:
    url: str
    title: str
    content: str
    token_count: int


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_page(page: Page, settings: Settings) -> list[Chunk]:
    """Split a page into overlapping character windows that respect paragraphs."""
    size = settings.chunk_chars
    overlap = settings.chunk_overlap_chars
    paragraphs = [p.strip() for p in page.text.split("\n") if p.strip()]

    chunks: list[Chunk] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 1 <= size:
            buffer = f"{buffer}\n{para}" if buffer else para
            continue
        if buffer:
            chunks.append(Chunk(page.url, page.title, buffer, _approx_tokens(buffer)))
        # Start the next buffer with a tail overlap for context continuity.
        tail = buffer[-overlap:] if overlap and buffer else ""
        buffer = f"{tail}\n{para}".strip() if tail else para
        # A single very long paragraph is hard split.
        while len(buffer) > size:
            head, buffer = buffer[:size], buffer[size - overlap :]
            chunks.append(Chunk(page.url, page.title, head, _approx_tokens(head)))
    if buffer.strip():
        chunks.append(Chunk(page.url, page.title, buffer.strip(), _approx_tokens(buffer)))
    return chunks


async def _embed_in_batches(
    texts: list[str], settings: Settings, batch_size: int = 64
) -> tuple[list[list[float] | None], int]:
    """Embed texts in batches. A batch that fails after retries yields None
    vectors for its texts instead of failing the whole ingest. Returns
    (vectors, failed_batches)."""
    vectors: list[list[float] | None] = []
    failed_batches = 0
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            vectors.extend(await embed_texts(batch, settings))
        except Exception:  # noqa: BLE001 - tenacity retries already applied
            log.exception("embedding batch %d-%d failed", i, i + len(batch))
            failed_batches += 1
            vectors.extend([None] * len(batch))
    return vectors, failed_batches


async def ingest_site(
    site_id: int, start_url: str, settings: Settings, full: bool = False
) -> tuple[int, int]:
    """Run the pipeline for one site. Returns (pages_crawled, chunks_written).

    full=True forces re-embedding everything (e.g. after changing the
    embedding model); otherwise only changed pages are processed.
    """
    started = time.monotonic()
    await store.set_site_status(site_id, "crawling")
    # A site may have additional seed URLs beyond start_url — crawl them all
    # into this one knowledge base.
    seeds = await store.get_seed_urls(site_id)
    # SPA-heavy sites can opt into Playwright rendering without changing the
    # platform default for everyone else.
    if await store.get_site_flag(site_id, "render_js"):
        settings = settings.model_copy(update={"use_browser": True})
    result = (
        await crawl_many(seeds, settings)
        if len(seeds) > 1
        else await crawl_site(start_url, settings)
    )
    pages = result.pages
    if not pages:
        await store.set_site_status(site_id, "error", "No content extracted from the site.")
        return 0, 0

    # Auto-branding: match the assistant to the client's site colour + font,
    # once, without overwriting any manual choices. Best-effort; never fatal.
    try:
        from sitebot import branding

        brand = await branding.extract_branding(start_url, settings)
        if brand:
            await store.apply_detected_branding(site_id, brand)
    except Exception:  # noqa: BLE001 - branding must never break ingestion
        log.warning("branding extraction failed for site %s", site_id)

    await store.set_site_status(site_id, "indexing")

    # Diff against the last crawl using content hashes.
    known = {} if full else await store.get_page_hashes(site_id)
    crawled_urls = {p.url for p in pages}
    hashes = {p.url: content_hash(p.text) for p in pages}
    changed = [p for p in pages if known.get(p.url) != hashes[p.url]]
    removed = sorted(set(known) - crawled_urls)

    # Chunk and embed only what changed.
    all_chunks: list[Chunk] = []
    for page in changed:
        all_chunks.extend(chunk_page(page, settings))

    vectors, failed_batches = await _embed_in_batches([c.content for c in all_chunks], settings)
    # A page is indexed all-or-nothing: any failed chunk keeps the whole page's
    # old chunks and old hash so the next run retries it cleanly.
    partial_urls = {c.url for c, emb in zip(all_chunks, vectors, strict=True) if emb is None}
    rows = [
        (c.url, c.title, c.content, c.token_count, emb)
        for c, emb in zip(all_chunks, vectors, strict=True)
        if emb is not None and c.url not in partial_urls
    ]
    embedded_urls = {r[0] for r in rows}

    await store.apply_incremental_index(
        site_id,
        rows=rows,
        changed_urls=sorted(embedded_urls),
        removed_urls=removed,
        page_hashes={p.url: (hashes[p.url], p.title) for p in pages if p.url in embedded_urls},
        seen_urls=sorted(crawled_urls),
        full=full,
    )

    report = {
        "pages_crawled": len(pages),
        "pages_changed": len(changed),
        "pages_removed": len(removed),
        "chunks_written": len(rows),
        "failed_urls": result.failed,
        "embed_batches_failed": failed_batches,
        "duration_s": round(time.monotonic() - started, 1),
        "mode": "full" if full else "incremental",
    }
    total_chunks = await store.count_chunks(site_id)
    await store.finalise_index(site_id, len(pages), total_chunks, report)
    if rows or removed:
        # Content changed; stale cached answers must not survive a refresh.
        await store.invalidate_cache(site_id)
        # Rebuild the entity graph so graph retrieval reflects the new content.
        try:
            from sitebot import graph

            await graph.rebuild_entity_index(site_id)
        except Exception:  # noqa: BLE001 - graph index is an enhancement
            log.warning("entity index rebuild failed for site %s", site_id)
    log.info(
        "ingest done site=%s pages=%d changed=%d removed=%d chunks=%d failed=%d",
        site_id, len(pages), len(changed), len(removed), len(rows), len(result.failed),
    )
    return len(pages), len(rows)
