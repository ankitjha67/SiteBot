"""Concurrent load test for the public chat endpoint.

Sends unique questions (cache-busting) from many concurrent clients and
reports throughput, latency percentiles, and an error breakdown. Run against
a site wired to a fast local model so the numbers measure SiteBot's own
pipeline (auth, rate limit, quota, embedding, hybrid retrieval, persistence),
not a remote LLM's latency.

    python scripts/loadtest.py --key pk_... [--n 600] [--concurrency 200]
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

QUESTIONS = [
    "How long is the warranty on grinders?",
    "How much does standard shipping cost?",
    "What is the pour-over recipe?",
    "When is the cafe open on Sunday?",
    "How long should cold brew steep?",
    "Do you ship to Canada?",
]


async def one_request(
    client: httpx.AsyncClient, base: str, key: str, i: int,
    latencies: list[float], errors: dict[str, int],
) -> None:
    # Unique suffix defeats the answer cache so every request runs the full
    # embed -> retrieve -> generate -> persist pipeline.
    question = f"{QUESTIONS[i % len(QUESTIONS)]} (load test #{i})"
    payload = {"key": key, "message": question, "visitor_id": f"loadtest-{i}"}
    start = time.perf_counter()
    try:
        resp = await client.post(f"{base}/v1/chat", json=payload)
        elapsed = time.perf_counter() - start
        if resp.status_code == 200:
            latencies.append(elapsed)
        else:
            errors[f"http_{resp.status_code}"] = errors.get(f"http_{resp.status_code}", 0) + 1
    except Exception as exc:  # noqa: BLE001
        errors[type(exc).__name__] = errors.get(type(exc).__name__, 0) + 1


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--key", required=True, help="Site public key (pk_...)")
    ap.add_argument("--n", type=int, default=600, help="Total requests")
    ap.add_argument("--concurrency", type=int, default=200)
    args = ap.parse_args()

    latencies: list[float] = []
    errors: dict[str, int] = {}
    sem = asyncio.Semaphore(args.concurrency)

    async def bounded(client: httpx.AsyncClient, i: int) -> None:
        async with sem:
            await one_request(client, args.base, args.key, i, latencies, errors)

    limits = httpx.Limits(max_connections=args.concurrency + 20)
    timeout = httpx.Timeout(120.0, connect=10.0)
    started = time.perf_counter()
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        await asyncio.gather(*(bounded(client, i) for i in range(args.n)))
    wall = time.perf_counter() - started

    ok = len(latencies)
    print(f"\nrequests: {args.n}  concurrency: {args.concurrency}")
    print(f"succeeded: {ok}  failed: {args.n - ok}")
    if errors:
        print("errors:", errors)
    if latencies:
        lat = sorted(latencies)
        def pct(p: float) -> float:
            return lat[min(len(lat) - 1, int(p * len(lat)))]
        print(f"wall time: {wall:.1f}s   throughput: {ok / wall:.1f} req/s")
        print(
            f"latency  p50: {statistics.median(lat)*1000:.0f}ms   "
            f"p95: {pct(0.95)*1000:.0f}ms   p99: {pct(0.99)*1000:.0f}ms   "
            f"max: {lat[-1]*1000:.0f}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
