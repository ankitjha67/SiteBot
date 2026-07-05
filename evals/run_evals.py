"""Answer-quality evaluation harness (Phase 3).

Runs a per-site eval set of question/expectation pairs against the live
pipeline (retrieval + answer) and reports pass/fail per case, so answer
quality regressions are caught before a release.

Eval file format (JSON):
[
  {"question": "How much is the Starter plan?",
   "must_contain": ["29"],                    # all substrings must appear
   "must_cite": "pricing",                    # optional: a source URL substring
   "expect_answer": true}                     # false = the bot should decline
]

Usage:
  python evals/run_evals.py --slug www-example-com --file evals/example_evals.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sitebot.config import get_settings
from sitebot.db import close_pool
from sitebot.rag import answer_stream
from sitebot.store import get_site_by_slug


async def run_case(site, case: dict) -> tuple[bool, str]:  # type: ignore[no-untyped-def]
    settings = get_settings()
    text_parts: list[str] = []
    sources: list[dict] = []
    async for ev in answer_stream(site, case["question"], settings, "eval", None):
        if ev["event"] == "token":
            text_parts.append(ev["data"])
        elif ev["event"] == "sources":
            sources = ev["data"]
    answer = "".join(text_parts)

    expect_answer = case.get("expect_answer", True)
    declined = "do not have" in answer.lower() and "knowledge base" in answer.lower()
    if not expect_answer:
        return (declined, "expected a decline" if not declined else "ok")
    if declined:
        return (False, "bot declined but an answer was expected")

    for needle in case.get("must_contain", []):
        if needle.lower() not in answer.lower():
            return (False, f"missing expected text: {needle!r}")
    cite = case.get("must_cite")
    if cite and not any(cite in s.get("url", "") for s in sources):
        return (False, f"no source URL containing {cite!r}")
    return (True, "ok")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    site = await get_site_by_slug(args.slug)
    if site is None:
        print(f"No site with slug {args.slug}")
        return 2
    cases = json.loads(Path(args.file).read_text(encoding="utf-8"))  # noqa: ASYNC240 - one-shot CLI

    passed = 0
    for i, case in enumerate(cases, start=1):
        ok, reason = await run_case(site, case)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {i}. {case['question']}  ({reason})")
        passed += ok
    print(f"\n{passed}/{len(cases)} passed")
    await close_pool()
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
