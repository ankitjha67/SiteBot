"""Offline unit tests. No database or network required.

Run: pip install -e ".[dev]" && pytest
"""

from __future__ import annotations

from sitebot.config import Settings
from sitebot.crawler import _dedupe_lines, _extract, _extract_links
from sitebot.ingest import chunk_page, content_hash

SAMPLE_HTML = """<html><head><title>Acme Pricing</title></head><body>
<nav>home about</nav>
<main><h1>Pricing</h1>
<p>Acme offers three plans. The Starter plan is $29 per month and includes 5 seats.</p>
<p>The Growth plan is $99 per month with 25 seats and priority support.</p>
<p>Enterprise pricing is custom. Contact sales for a quote and onboarding help.</p>
</main>
<a href="/features">Features</a>
<a href="https://acme.com/contact">Contact</a>
<a href="https://other-site.com/x">External</a>
<a href="/logo.png">Logo</a>
</body></html>"""


def test_extract_returns_title_and_body() -> None:
    page = _extract("https://acme.com/pricing", SAMPLE_HTML)
    assert page is not None
    assert page.title == "Acme Pricing"
    assert "Starter plan" in page.text


def test_links_are_same_site_and_non_asset() -> None:
    links = _extract_links("https://acme.com/pricing", SAMPLE_HTML, "acme.com")
    assert "https://acme.com/features" in links
    assert "https://acme.com/contact" in links
    assert all("other-site.com" not in link for link in links)
    assert all(not link.endswith(".png") for link in links)


def test_dedupe_removes_repeated_lines() -> None:
    text = "one\ntwo\ntwo\nthree\none"
    assert _dedupe_lines(text) == "one\ntwo\nthree"


def test_chunking_produces_bounded_chunks() -> None:
    page = _extract("https://acme.com/pricing", SAMPLE_HTML)
    assert page is not None
    settings = Settings(chunk_chars=120, chunk_overlap_chars=30)
    chunks = chunk_page(page, settings)
    assert len(chunks) >= 1
    for chunk in chunks:
        # Allow a small margin for overlap and paragraph boundaries.
        assert len(chunk.content) <= 120 * 2
        assert chunk.token_count > 0


def test_content_hash_is_stable_and_sensitive() -> None:
    assert content_hash("hello") == content_hash("hello")
    assert content_hash("hello") != content_hash("hello!")
