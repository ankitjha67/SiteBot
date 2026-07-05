"""Semantic re-ranking with a cross-encoder.

Bi-encoder retrieval (the embedding search) scores question and chunk
independently; a cross-encoder reads them together and is markedly better at
"does this passage actually answer this question". We retrieve wide
(2 x top_k via RRF) and let the cross-encoder pick the final top_k.

Opt-in via RERANK_ENABLED because the model (~90 MB) downloads on first use
and adds ~50-150 ms per query on CPU. Failures fall back to the RRF order -
reranking must never break answering.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from sitebot.config import Settings
from sitebot.store import RetrievedChunk

log = logging.getLogger(__name__)

_gate = asyncio.Semaphore(2)  # bound concurrent CPU-heavy rerank calls


@lru_cache(maxsize=1)
def _model(name: str):  # type: ignore[no-untyped-def]
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name)


async def rerank(
    question: str, chunks: list[RetrievedChunk], top_k: int, settings: Settings
) -> list[RetrievedChunk]:
    if not settings.rerank_enabled or len(chunks) <= 1:
        return chunks[:top_k]
    try:
        model = _model(settings.rerank_model)
        pairs = [(question, c.content[:1500]) for c in chunks]

        def _run() -> list[float]:
            return [float(s) for s in model.predict(pairs)]

        async with _gate:
            scores = await asyncio.to_thread(_run)
        ranked = sorted(zip(chunks, scores, strict=True), key=lambda x: x[1], reverse=True)
        return [c for c, _ in ranked[:top_k]]
    except Exception:  # noqa: BLE001 - reranking is an enhancement, not a gate
        log.exception("rerank failed; falling back to fused order")
        return chunks[:top_k]
