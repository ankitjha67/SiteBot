"""Entity-graph retrieval for multi-hop questions.

Pure vector/keyword retrieval finds chunks similar to the *question*. Some
questions need facts about a *named thing* that live in a chunk the question
doesn't textually resemble ("which SUV has the longest warranty and its price?"
— the price and the warranty may be in different passages linked only by the
vehicle name). Graph retrieval bridges that:

1. At index time we extract entities (proper-noun / model-code phrases) from
   each chunk and record which chunks mention them (entity_mentions).
2. Two entities that appear in the same chunk are "connected".
3. At query time we pull chunks that mention the question's entities, then
   1-hop out to chunks mentioning entities that co-occur with them — surfacing
   connected facts. These are fused with hybrid retrieval, never replacing it.

Entity extraction is deliberately dependency-free (no spaCy/LLM, so indexing
stays free and fast): capitalized multi-word phrases plus alphanumeric model
codes. It can be upgraded to LLM/NER later without changing the retrieval path.
"""

from __future__ import annotations

import logging
import re

from sitebot.db import get_pool
from sitebot.store import RetrievedChunk

log = logging.getLogger(__name__)

# Capitalized phrases (Alpine X5 Hybrid, Northern Lights, Summit Auto Group)
# and standalone model/spec codes (X5, EV9, RTX4090).
_PROPER = re.compile(r"\b([A-Z][a-zA-Z0-9]*(?:\s+[A-Z0-9][a-zA-Z0-9]*){0,3})\b")
_CODE = re.compile(r"\b([A-Z]{1,4}[- ]?\d{1,5}[A-Za-z]{0,3})\b")
_STOP_ENTITIES = {
    "the", "a", "an", "we", "our", "you", "your", "this", "that", "it", "i",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}


def _trim(words: list[str]) -> list[str]:
    """Drop leading determiners/years and trailing stopwords so the same thing
    normalizes the same way in a document and in a question ('The 2026 Alpine
    X5' and 'Alpine X5' both -> 'alpine x5')."""
    while words and (words[0].lower() in _STOP_ENTITIES or words[0].isdigit()):
        words = words[1:]
    while words and words[-1].lower() in _STOP_ENTITIES:
        words = words[:-1]
    return words


def extract_entities(text: str) -> dict[str, str]:
    """Return {normalized_name: display_name} of entities found in text."""
    out: dict[str, str] = {}
    for m in _PROPER.finditer(text):
        words = _trim(m.group(1).split())
        if not words:
            continue
        phrase = " ".join(words)
        norm = phrase.lower()
        # Keep multi-word phrases, or single words 4+ chars (proper nouns).
        if norm in _STOP_ENTITIES or len(norm) < 3:
            continue
        if len(words) >= 2 or len(phrase) >= 4:
            out.setdefault(norm, phrase)
    for m in _CODE.finditer(text):
        code = m.group(1).strip()
        out.setdefault(code.lower(), code)
    return out


async def rebuild_entity_index(site_id: int) -> int:
    """Recompute the entity graph for a site from its current chunks. Called
    after each crawl. Returns the number of entities indexed."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM entities WHERE site_id = $1", site_id)
        rows = await conn.fetch(
            "SELECT id, content FROM chunks WHERE site_id = $1", site_id
        )
        name_to_id: dict[str, int] = {}
        mentions: list[tuple[int, int, int]] = []
        for r in rows:
            ents = extract_entities(r["content"])
            for norm, display in ents.items():
                eid = name_to_id.get(norm)
                if eid is None:
                    eid = await conn.fetchval(
                        "INSERT INTO entities (site_id, name, display) VALUES ($1,$2,$3) "
                        "ON CONFLICT (site_id, name) DO UPDATE SET display = EXCLUDED.display "
                        "RETURNING id",
                        site_id, norm, display,
                    )
                    name_to_id[norm] = eid
                mentions.append((eid, r["id"], site_id))
        if mentions:
            await conn.executemany(
                "INSERT INTO entity_mentions (entity_id, chunk_id, site_id) "
                "VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                mentions,
            )
    log.info("entity index rebuilt for site %s: %d entities", site_id, len(name_to_id))
    return len(name_to_id)


async def graph_retrieve(site_id: int, question: str, top_k: int) -> list[RetrievedChunk]:
    """Entity-linked retrieval: chunks that mention the question's entities plus
    a 1-hop expansion to co-occurring entities. Ranked by how many question and
    connected entities each chunk carries. Empty when no entities match."""
    q_ents = list(extract_entities(question).keys())
    if not q_ents:
        return []
    pool = await get_pool()
    ent_rows = await pool.fetch(
        "SELECT id FROM entities WHERE site_id = $1 AND name = ANY($2::text[])",
        site_id, q_ents,
    )
    ent_ids = [r["id"] for r in ent_rows]
    if not ent_ids:
        return []
    # Chunks directly mentioning the question's entities.
    direct = await pool.fetch(
        "SELECT DISTINCT chunk_id FROM entity_mentions "
        "WHERE site_id = $1 AND entity_id = ANY($2::bigint[])",
        site_id, ent_ids,
    )
    direct_chunks = [r["chunk_id"] for r in direct]
    if not direct_chunks:
        return []
    # 1-hop: entities that co-occur in those chunks, then the chunks THEY appear
    # in. This is what surfaces connected facts.
    hop_rows = await pool.fetch(
        "SELECT em.chunk_id, count(*) AS hits FROM entity_mentions em "
        "WHERE em.site_id = $1 AND em.entity_id IN ("
        "  SELECT DISTINCT entity_id FROM entity_mentions "
        "  WHERE chunk_id = ANY($2::bigint[])"
        ") GROUP BY em.chunk_id ORDER BY hits DESC LIMIT $3",
        site_id, direct_chunks, top_k * 3,
    )
    # Score: direct-mention chunks weigh more than 1-hop-only chunks.
    direct_set = set(direct_chunks)
    scored: dict[int, float] = {}
    for r in hop_rows:
        cid = r["chunk_id"]
        scored[cid] = r["hits"] + (2.0 if cid in direct_set else 0.0)
    top_ids = sorted(scored, key=lambda c: scored[c], reverse=True)[:top_k]
    if not top_ids:
        return []
    chunk_rows = await pool.fetch(
        "SELECT id, url, title, content FROM chunks WHERE id = ANY($1::bigint[])", top_ids
    )
    by_id = {r["id"]: r for r in chunk_rows}
    out: list[RetrievedChunk] = []
    maxs = max(scored.values()) or 1.0
    for cid in top_ids:
        r = by_id.get(cid)
        if r is not None:
            out.append(RetrievedChunk(
                url=r["url"], title=r["title"], content=r["content"],
                score=round(scored[cid] / maxs, 4),
            ))
    return out
