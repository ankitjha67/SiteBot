"""Embedding providers. Swap between a hosted API and a local model via config.

Important: the vector dimension is tied to the model. If you change the model,
update EMBED_DIM and the vector(N) columns in sql/schema.sql to match.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from tenacity import retry, stop_after_attempt, wait_exponential

from sitebot.config import Settings


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20))
async def _embed_openai(texts: list[str], settings: Settings) -> list[list[float]]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.embeddings.create(model=settings.openai_embed_model, input=texts)
    return [d.embedding for d in resp.data]


@lru_cache(maxsize=1)
def _local_model(model_name: str):  # type: ignore[no-untyped-def]
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


# Bound concurrent encodes: under a burst of chat requests, unbounded
# to_thread calls all fight for the same CPU cores and every request slows
# down. A small bound keeps per-request latency predictable; excess requests
# queue here instead of thrashing.
_encode_gate: asyncio.Semaphore | None = None


def _gate(settings: Settings) -> asyncio.Semaphore:
    global _encode_gate
    if _encode_gate is None:
        _encode_gate = asyncio.Semaphore(max(1, settings.embed_concurrency))
    return _encode_gate


async def _embed_local(texts: list[str], settings: Settings) -> list[list[float]]:
    model = _local_model(settings.local_embed_model)

    def _run() -> list[list[float]]:
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [v.tolist() for v in vectors]

    async with _gate(settings):
        return await asyncio.to_thread(_run)


async def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    """Return one embedding vector per input text."""
    if not texts:
        return []
    if settings.embed_provider == "local":
        return await _embed_local(texts, settings)
    return await _embed_openai(texts, settings)


async def embed_query(text: str, settings: Settings) -> list[float]:
    vectors = await embed_texts([text], settings)
    return vectors[0]
