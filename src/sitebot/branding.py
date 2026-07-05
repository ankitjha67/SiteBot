"""Auto-branding: detect a site's colour and font while crawling, so the
assistant matches each client's brand without any manual setup.

We fetch the homepage HTML once and read the strongest brand signals:
- colour: <meta name="theme-color">, else the most common saturated colour in
  inline styles / <style> blocks (buttons, links, headers use it), else none.
- font:   a Google Fonts <link> family, else the first named font-family in CSS.

Everything is best-effort: any failure returns empty values and the widget
keeps its defaults. Detected values are applied only when the operator hasn't
already chosen their own (see ingest.apply_branding).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

import httpx

from sitebot.config import Settings

log = logging.getLogger(__name__)

_DEFAULT_COLORS = {"#fff", "#ffffff", "#000", "#000000"}
_HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
_THEME_META_RE = re.compile(
    r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
_GFONTS_RE = re.compile(
    r'fonts\.googleapis\.com/css2?\?([^"\'>]+)', re.I
)
_FONT_FAMILY_RE = re.compile(r'font-family\s*:\s*([^;{}"\']+)', re.I)
_VALID_FONT_RE = re.compile(r"[A-Za-z][A-Za-z0-9 _-]{1,40}")
# Generic families we never want to advertise as "the brand font".
_GENERIC_FONTS = {
    "sans-serif", "serif", "monospace", "system-ui", "inherit", "initial",
    "-apple-system", "blinkmacsystemfont", "ui-sans-serif", "ui-serif", "arial",
    "helvetica", "roboto", "segoe ui", "cursive",
}
# Icon fonts are decorative glyph sets, never a site's text/brand font.
_ICON_FONTS = ("material symbols", "material icons", "font awesome",
               "fontawesome", "ionicons", "glyphicon", "feather")


def _is_icon_font(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _ICON_FONTS)


def _hex6(h: str) -> str:
    h = h.lower()
    if len(h) == 4:  # #abc -> #aabbcc
        h = "#" + "".join(c * 2 for c in h[1:])
    return h


def _saturation(hex6: str) -> float:
    """0 = grey/black/white, 1 = fully saturated. Used to skip neutral colours."""
    r, g, b = (int(hex6[i : i + 2], 16) for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def detect_color(html: str) -> str:
    m = _THEME_META_RE.search(html)
    if m:
        c = m.group(1).strip()
        if _HEX_RE.fullmatch(c):
            return _hex6(c)
    # Fall back to the most common saturated colour in styles.
    counts: dict[str, int] = {}
    for raw in _HEX_RE.findall(html):
        h = _hex6("#" + raw)
        if h in _DEFAULT_COLORS or _saturation(h) < 0.25:
            continue
        counts[h] = counts.get(h, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda k: counts[k])


def detect_font(html: str) -> tuple[str, str]:
    """Return (family_name, google_fonts_url). Empty strings if none found.
    Skips icon fonts (Material Symbols, Font Awesome, ...) which are glyph
    sets, not a site's text font."""
    for m in _GFONTS_RE.finditer(html):
        query = unquote(m.group(1))
        for fam in re.findall(r"family=([^:&]+)", query):
            family = fam.replace("+", " ").strip()
            low = family.lower()
            if not family or low in _GENERIC_FONTS or _is_icon_font(family):
                continue
            base = "family=" + fam.split(":")[0]
            url = "https://fonts.googleapis.com/css2?" + base + "&display=swap"
            return family, url
    # Fall back to the first non-generic named font-family in CSS.
    for decl in _FONT_FAMILY_RE.findall(html):
        for name in decl.split(","):
            name = name.strip().strip("'\"")
            # A real font name starts with a letter and is plain text — this
            # rejects var(...), HTML entities (&#x27;), and other junk.
            if (
                _VALID_FONT_RE.fullmatch(name) and name.lower() not in _GENERIC_FONTS
                and not _is_icon_font(name)
            ):
                return name, ""
    return "", ""


async def extract_branding(url: str, settings: Settings) -> dict[str, str]:
    """Fetch the homepage and return {'color', 'font', 'font_url'} (any empty)."""
    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout_s, follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return {}
        html = resp.text[:400_000]  # header + early CSS is enough
    except httpx.HTTPError:
        return {}
    color = detect_color(html)
    font, font_url = detect_font(html)
    result = {k: v for k, v in {"color": color, "font": font, "font_url": font_url}.items() if v}
    if result:
        log.info("branding detected for %s: %s", url, result)
    return result
