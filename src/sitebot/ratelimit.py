"""Rate limiting and monthly quota enforcement.

With REDIS_URL set, limits are shared across processes and survive restarts
(fixed one-minute windows via INCR + EXPIRE). Without Redis, an in-memory
sliding window is used, suitable only for a single dev instance.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException

from sitebot.config import Settings
from sitebot.db import get_pool

_redis = None  # lazily created shared client


async def _get_redis(settings: Settings):  # type: ignore[no-untyped-def]
    global _redis
    if _redis is None and settings.redis_url:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


# ------------------------- in-memory fallback -------------------------
_HITS: dict[str, deque[float]] = defaultdict(deque)


def _memory_allow(key: str, limit: int, window_s: float = 60.0) -> bool:
    now = time.monotonic()
    bucket = _HITS[key]
    while bucket and now - bucket[0] > window_s:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


async def enforce_rate_limit(key: str, settings: Settings) -> None:
    """Raise 429 when the caller exceeds the per-minute limit."""
    limit = settings.rate_limit_per_minute
    redis = await _get_redis(settings)
    if redis is None:
        allowed = _memory_allow(key, limit)
    else:
        window = int(time.time() // 60)
        rkey = f"rl:{key}:{window}"
        count = await redis.incr(rkey)
        if count == 1:
            await redis.expire(rkey, 90)
        allowed = count <= limit
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Slow down.")


async def enforce_monthly_quota(tenant_id: int, plan: str, settings: Settings) -> None:
    """Raise 429 when the tenant used up its monthly answered-message quota."""
    quota = settings.plan_quotas.get(plan, 0)
    if quota <= 0:  # unlimited or unknown plan
        return
    pool = await get_pool()
    used = await pool.fetchval(
        "SELECT count(*) FROM usage_events "
        "WHERE tenant_id = $1 AND kind = 'message' "
        "AND created_at >= date_trunc('month', now())",
        tenant_id,
    )
    if used is not None and used >= quota:
        raise HTTPException(
            status_code=429,
            detail="Monthly message quota reached for this site. Upgrade the plan to continue.",
        )
