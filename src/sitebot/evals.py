"""Answer-quality evaluation harness.

The point: know whether a change (chunking, retrieval, prompt, model) made the
bot better or worse BEFORE customers do. Run it after every meaningful change
and in CI against a seeded test site.

An eval set is a JSON file of golden questions:

    [
      {
        "question": "How long is the grinder warranty?",
        "expect_url": "warranty",           # substring of a top-k source URL
        "expect_any": ["3 year", "3-year"]  # any must appear in retrieved text
      },
      ...
    ]

Two modes:
- retrieval (default): checks the retriever alone - does the right page rank
  in the top-k, and do the retrieved chunks contain the expected facts?
  Free, fast, deterministic. This is the metric that moves answer quality.
- --answers: additionally runs the full RAG pipeline (LLM included) and checks
  expect_any against the generated answer and expect_url against the citations.
  Costs model calls; run it on a schedule, not every commit.

Exit code is non-zero when the pass rate is below --threshold, so it works as
a CI gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sitebot import store
from sitebot.config import Settings
from sitebot.rag import answer_stream, retrieve


@dataclass(slots=True)
class EvalCase:
    question: str
    expect_url: str = ""
    expect_any: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CaseResult:
    case: EvalCase
    url_hit: bool
    content_hit: bool
    answer_hit: bool | None = None  # None when answer mode is off
    cited_ok: bool | None = None
    top_urls: list[str] = field(default_factory=list)
    answer: str = ""

    @property
    def passed(self) -> bool:
        retrieval_ok = (self.url_hit or not self.case.expect_url) and (
            self.content_hit or not self.case.expect_any
        )
        if self.answer_hit is None:
            return retrieval_ok
        answer_ok = (self.answer_hit or not self.case.expect_any) and (
            self.cited_ok or not self.case.expect_url
        )
        return retrieval_ok and answer_ok


def load_eval_set(path: str | Path) -> list[EvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for item in raw:
        cases.append(
            EvalCase(
                question=str(item["question"]),
                expect_url=str(item.get("expect_url", "")),
                expect_any=[str(s) for s in item.get("expect_any", [])],
            )
        )
    return cases


def _contains_any(haystack: str, needles: list[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles)


async def _run_answer(site, case: EvalCase, settings: Settings) -> tuple[str, list[str]]:
    """Run the full pipeline for one question; return (answer, cited urls)."""
    parts: list[str] = []
    cited: list[str] = []
    async for ev in answer_stream(site, case.question, settings, None, None):
        if ev["event"] == "token":
            parts.append(ev["data"])
        elif ev["event"] == "sources":
            cited = [s.get("url", "") for s in ev["data"]]
    return "".join(parts), cited


async def run_eval(
    slug: str,
    cases: list[EvalCase],
    settings: Settings,
    answers: bool = False,
) -> list[CaseResult]:
    site = await store.get_site_by_slug(slug)
    if site is None:
        raise RuntimeError(f"No site with slug {slug!r}.")

    results: list[CaseResult] = []
    for case in cases:
        chunks = await retrieve(site.id, case.question, settings)
        top_urls = [c.url for c in chunks]
        retrieved_text = "\n".join(c.content for c in chunks)
        url_hit = bool(case.expect_url) and any(
            case.expect_url.lower() in u.lower() for u in top_urls
        )
        content_hit = bool(case.expect_any) and _contains_any(retrieved_text, case.expect_any)

        result = CaseResult(
            case=case, url_hit=url_hit, content_hit=content_hit, top_urls=top_urls
        )
        if answers:
            answer, cited = await _run_answer(site, case, settings)
            result.answer = answer
            result.answer_hit = _contains_any(answer, case.expect_any)
            result.cited_ok = bool(case.expect_url) and any(
                case.expect_url.lower() in u.lower() for u in cited
            )
        results.append(result)
    return results


def format_report(results: list[CaseResult], answers: bool) -> str:
    lines: list[str] = []
    passed = sum(1 for r in results if r.passed)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"[{status}] {r.case.question}")
        if not r.passed:
            if r.case.expect_url and not r.url_hit:
                lines.append(f"    expected url ~{r.case.expect_url!r} in top-k; "
                             f"got: {r.top_urls[:3]}")
            if r.case.expect_any and not r.content_hit:
                lines.append(f"    expected one of {r.case.expect_any} in retrieved text")
            if answers and r.answer_hit is False:
                lines.append(f"    answer missed expected facts: {r.answer[:160]!r}")
            if answers and r.cited_ok is False:
                lines.append(f"    answer did not cite ~{r.case.expect_url!r}")
    mode = "retrieval+answers" if answers else "retrieval"
    rate = passed / len(results) if results else 0.0
    lines.append(f"\n{passed}/{len(results)} passed ({rate:.0%}) - mode: {mode}")
    return "\n".join(lines)


def pass_rate(results: list[CaseResult]) -> float:
    return sum(1 for r in results if r.passed) / len(results) if results else 0.0
