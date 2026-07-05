"""Website crawler and content extractor.

Discovers URLs from sitemap.xml (including sitemap indexes) and by following
in-page links, fetches pages concurrently but politely, and extracts clean
main-body text with trafilatura. JavaScript-rendered pages are supported when
the browser extra is installed and USE_BROWSER is on.

Concurrency model: CRAWL_CONCURRENCY fetches run in flight at once; link
extraction and frontier bookkeeping happen in the single driver coroutine, so
no locks are needed. Transient network failures are retried once. trafilatura
extraction is CPU-bound and runs in a thread so it never blocks the event loop.

Returns a CrawlResult that includes per-URL failures so ingestion can produce a
failed-URL report instead of silently dropping pages.
"""

from __future__ import annotations

import asyncio
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import trafilatura
from lxml import html as lxml_html

from sitebot.config import Settings

_SKIP_EXTENSIONS = (
    ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".css", ".js", ".ico", ".woff", ".woff2", ".ttf",
)
_MAX_PDF_BYTES = 15 * 1024 * 1024

# Exceptions worth one retry: the server or network hiccuped, not a hard "no".
_TRANSIENT = (
    httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout,
    httpx.RemoteProtocolError, httpx.PoolTimeout, httpx.ReadError,
)


@dataclass(slots=True)
class Page:
    url: str
    title: str
    text: str


@dataclass(slots=True)
class CrawlResult:
    pages: list[Page] = field(default_factory=list)
    # url -> reason ("fetch_error", "http_403", "no_content", "robots")
    failed: dict[str, str] = field(default_factory=dict)


def _norm_netloc(netloc: str) -> str:
    """www.acme.com and acme.com are the same site for crawling purposes."""
    n = netloc.lower()
    return n[4:] if n.startswith("www.") else n


def _same_site(url: str, root_netloc: str) -> bool:
    netloc = _norm_netloc(urlparse(url).netloc)
    root = _norm_netloc(root_netloc)
    return netloc == root or netloc.endswith("." + root)


def _clean_url(url: str) -> str:
    return urldefrag(url)[0].rstrip("/")


def _looks_crawlable(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not path.endswith(_SKIP_EXTENSIONS)


async def _load_robots(
    client: httpx.AsyncClient, base: str
) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = await client.get(urljoin(base, "/robots.txt"))
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        else:
            rp.allow_all = True
    except httpx.HTTPError:
        rp.allow_all = True
    return rp


def _parse_sitemap(content: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls) from one sitemap document."""
    try:
        tree = lxml_html.fromstring(content)
    except ValueError:
        return [], []
    pages: list[str] = []
    children: list[str] = []
    # A sitemap index nests <loc> inside <sitemap>; a urlset inside <url>.
    for loc in tree.xpath("//*[local-name()='sitemap']/*[local-name()='loc']/text()"):
        children.append(str(loc).strip())
    for loc in tree.xpath("//*[local-name()='url']/*[local-name()='loc']/text()"):
        pages.append(_clean_url(str(loc).strip()))
    if not pages and not children:
        # Lenient fallback: bare <loc> elements without the standard nesting.
        pages = [
            _clean_url(str(loc).strip())
            for loc in tree.xpath("//*[local-name()='loc']/text()")
        ]
    return pages, children


async def _sitemap_urls(
    client: httpx.AsyncClient, base: str, settings: Settings
) -> list[str]:
    """Fetch sitemap.xml (best effort), following sitemap indexes one level
    deep, capped so a huge sitemap cannot stall the crawl."""
    cap = settings.max_pages * 3
    urls: list[str] = []
    try:
        resp = await client.get(urljoin(base, "/sitemap.xml"))
        if resp.status_code != 200:
            return urls
        pages, children = _parse_sitemap(resp.content)
        urls.extend(pages[:cap])
        for child in children[:10]:  # sitemap index: fetch up to 10 children
            if len(urls) >= cap:
                break
            try:
                child_resp = await client.get(child)
                if child_resp.status_code == 200:
                    child_pages, _ = _parse_sitemap(child_resp.content)
                    urls.extend(child_pages[: cap - len(urls)])
            except httpx.HTTPError:
                continue
    except httpx.HTTPError:
        return urls
    return urls


async def _fetch_static(
    client: httpx.AsyncClient, url: str, settings: Settings
) -> tuple[str | None, str]:
    """Return (html, failure_reason). Retries transient failures once."""
    for attempt in (1, 2):
        try:
            resp = await client.get(url)
        except _TRANSIENT as exc:
            if attempt == 1:
                await asyncio.sleep(1.0)
                continue
            return None, f"fetch_error:{type(exc).__name__}"
        except httpx.HTTPError as exc:
            return None, f"fetch_error:{type(exc).__name__}"
        if resp.status_code in (429, 502, 503, 504) and attempt == 1:
            await asyncio.sleep(2.0)
            continue
        if resp.status_code != 200:
            return None, f"http_{resp.status_code}"
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and ctype != "":
            return None, "not_html"
        return resp.text, ""
    return None, "fetch_error"


async def _fetch_rendered(url: str, settings: Settings) -> str | None:
    """Render a page with Playwright. Requires the browser extra."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(user_agent=settings.user_agent)
            timeout_ms = int(settings.request_timeout_s * 1000)
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            content = await page.content()
            await browser.close()
            return content
    except Exception:
        return None


def _dedupe_lines(text: str) -> str:
    """Drop exact duplicate lines, preserving order. Guards against extractors
    that occasionally emit the same block twice."""
    seen: set[str] = set()
    out: list[str] = []
    for line in text.split("\n"):
        key = line.strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(line)
    return "\n".join(out)


def _extract(url: str, raw_html: str) -> Page | None:
    text = trafilatura.extract(
        raw_html,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        url=url,
    )
    if not text or len(text.strip()) < 120:
        return None
    text = _dedupe_lines(text.strip())
    title = ""
    try:
        doc = lxml_html.fromstring(raw_html)
        found = doc.xpath("//title/text()")
        if found:
            title = str(found[0]).strip()
    except ValueError:
        title = ""
    return Page(url=url, title=title, text=text.strip())


def _extract_links(base_url: str, raw_html: str, root_netloc: str) -> list[str]:
    out: list[str] = []
    try:
        doc = lxml_html.fromstring(raw_html)
    except ValueError:
        return out
    for href in doc.xpath("//a/@href"):
        candidate = _clean_url(urljoin(base_url, str(href)))
        if not candidate.startswith(("http://", "https://")):
            continue
        if _same_site(candidate, root_netloc) and _looks_crawlable(candidate):
            out.append(candidate)
    return out


async def crawl_many(urls: list[str], settings: Settings) -> CrawlResult:
    """Crawl several seed URLs (each within its own domain scope) and merge the
    pages into one result, deduping by URL and capping total at MAX_PAGES. Lets
    one client bot learn from multiple websites into a single knowledge base."""
    merged = CrawlResult()
    seen: set[str] = set()
    for seed in urls:
        if not seed or len(merged.pages) >= settings.max_pages:
            break
        res = await crawl_site(seed, settings)
        for page in res.pages:
            if page.url not in seen and len(merged.pages) < settings.max_pages:
                seen.add(page.url)
                merged.pages.append(page)
        merged.failed.update(res.failed)
    return merged


async def _process_one(
    client: httpx.AsyncClient,
    url: str,
    robots: urllib.robotparser.RobotFileParser,
    settings: Settings,
) -> tuple[str, Page | None, list[str], str]:
    """Fetch, extract, and collect links for one URL.

    Returns (url, page_or_None, links, failure_reason). Runs concurrently;
    everything returned is merged by the single driver coroutine.
    """
    if not robots.can_fetch(settings.user_agent, url):
        return url, None, [], "robots"
    if settings.crawl_delay_s:
        await asyncio.sleep(settings.crawl_delay_s)

    # Linked PDFs (price lists, manuals, datasheets) join the knowledge base.
    if urlparse(url).path.lower().endswith(".pdf"):
        try:
            resp = await client.get(url)
            if resp.status_code != 200 or len(resp.content) > _MAX_PDF_BYTES:
                return url, None, [], f"pdf_http_{resp.status_code}"
            from sitebot.sources import extract_text

            text = await asyncio.to_thread(extract_text, "page.pdf", resp.content)
            if len(text.strip()) < 120:
                return url, None, [], "no_content"
            title = url.rsplit("/", 1)[-1]
            return url, Page(url=url, title=title, text=text.strip()), [], ""
        except Exception:  # noqa: BLE001 - a bad PDF must not kill the crawl
            return url, None, [], "pdf_error"

    raw, reason = await _fetch_static(client, url, settings)
    if raw is None and settings.use_browser:
        raw = await _fetch_rendered(url, settings)
    if raw is None:
        return url, None, [], reason or "fetch_error"

    # trafilatura + lxml are CPU-bound; keep them off the event loop.
    root_netloc = urlparse(url).netloc.lower()
    page = await asyncio.to_thread(_extract, url, raw)
    links = await asyncio.to_thread(_extract_links, url, raw, root_netloc)
    if page is None:
        return url, None, links, "no_content"
    return url, page, links, ""


async def crawl_site(start_url: str, settings: Settings) -> CrawlResult:
    """Crawl a site starting at start_url and return extracted pages + failures.

    Honours robots.txt, seeds from sitemap.xml (following sitemap indexes),
    fetches CRAWL_CONCURRENCY pages in flight, and caps at MAX_PAGES.
    """
    start_url = _clean_url(start_url)
    root_netloc = urlparse(start_url).netloc.lower()
    concurrency = max(1, settings.crawl_concurrency)

    limits = httpx.Limits(
        max_connections=concurrency * 2, max_keepalive_connections=concurrency
    )
    result = CrawlResult()
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.request_timeout_s,
        limits=limits,
        headers={"User-Agent": settings.user_agent},
    ) as client:
        robots = await _load_robots(client, start_url)

        seen: set[str] = set()
        frontier: deque[str] = deque()
        for u in [start_url, *await _sitemap_urls(client, start_url, settings)]:
            cu = _clean_url(u)
            if cu not in seen and _same_site(cu, root_netloc) and _looks_crawlable(cu):
                seen.add(cu)
                frontier.append(cu)

        in_flight: set[asyncio.Task] = set()
        try:
            while (frontier or in_flight) and len(result.pages) < settings.max_pages:
                # Keep the pipeline full without overshooting the page cap.
                budget = settings.max_pages - len(result.pages) - len(in_flight)
                while frontier and len(in_flight) < concurrency and budget > 0:
                    url = frontier.popleft()
                    in_flight.add(
                        asyncio.create_task(_process_one(client, url, robots, settings))
                    )
                    budget -= 1
                if not in_flight:
                    break

                done, in_flight = await asyncio.wait(
                    in_flight, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    url, page, links, reason = task.result()
                    if page is not None:
                        if len(result.pages) < settings.max_pages:
                            result.pages.append(page)
                    elif reason:
                        result.failed[url] = reason
                    for link in links:
                        if link not in seen and len(seen) < settings.max_pages * 3:
                            seen.add(link)
                            frontier.append(link)
        finally:
            for task in in_flight:
                task.cancel()

    return result
