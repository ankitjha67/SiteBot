"""One-time migration: encrypt plaintext client secrets already in the DB.

Idempotent - already-encrypted values (enc:v1: prefix) are skipped, so it is
safe to run repeatedly. Requires SECRET_ENCRYPTION_KEY to be set.

    python scripts/encrypt_existing_secrets.py
"""

from __future__ import annotations

import asyncio
import json

from sitebot.config import get_settings
from sitebot.crypto import encrypt_secret
from sitebot.db import close_pool, get_pool
from sitebot.store import SECRET_COLUMNS


async def main() -> None:
    if not get_settings().secret_encryption_key:
        raise SystemExit("Set SECRET_ENCRYPTION_KEY first (see docs/DEPLOYMENT_GUIDE.md).")
    pool = await get_pool()
    cols = ", ".join(SECRET_COLUMNS)
    rows = await pool.fetch(f"SELECT id, {cols}, protected_secrets FROM sites")
    migrated = 0
    for row in rows:
        sets, values = [], []
        for col in SECRET_COLUMNS:
            v = row[col]
            if v and not v.startswith("enc:v1:"):
                sets.append(col)
                values.append(encrypt_secret(v))
        ps = row["protected_secrets"]
        ps = json.loads(ps) if isinstance(ps, str) else (ps or [])
        if any(s and not s.startswith("enc:v1:") for s in ps):
            sets.append("protected_secrets")
            values.append(json.dumps([encrypt_secret(s) for s in ps]))
        if not sets:
            continue
        assign = ", ".join(f"{c} = ${i}" for i, c in enumerate(sets, start=2))
        await pool.execute(
            f"UPDATE sites SET {assign}, updated_at = now() WHERE id = $1",
            row["id"], *values,
        )
        migrated += 1
    print(f"encrypted secrets on {migrated} site(s); {len(rows) - migrated} already clean")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
