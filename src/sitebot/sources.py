"""Knowledge sources beyond the crawler: uploaded files, raw text, Q&A pairs.

Each source gets a source:// pseudo-URL used as chunks.url, which keeps
retrieval, citation labelling, and deletion uniform with crawled pages.
Uploaded sources survive full site re-indexing (see store.apply_incremental_index).
"""

from __future__ import annotations

import re
import secrets

from sitebot import store
from sitebot.config import Settings
from sitebot.crawler import Page
from sitebot.db import get_pool
from sitebot.embeddings import embed_texts
from sitebot.ingest import chunk_page

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".html", ".htm", ".json"}

# Pull INSERT rows out of a SQL dump into readable "table: col=val" lines.
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+[`\"']?(?P<table>\w+)[`\"']?\s*"
    r"(?:\((?P<cols>[^)]*)\))?\s*VALUES\s*(?P<vals>.+?);",
    re.IGNORECASE | re.DOTALL,
)
_ROW_RE = re.compile(r"\(((?:[^()']|'(?:[^'\\]|\\.)*')*)\)", re.DOTALL)


def sql_dump_to_text(sql: str) -> str:
    """Convert a database dump into readable sentences the retriever can use.

    Each INSERTed row becomes 'In table <t>: <col> is <val>; ...'. This lets
    the bot answer from structured data (orders, products, FAQs stored in a DB)
    without running the database. Falls back to raw text if nothing parses.
    """
    lines: list[str] = []
    for m in _INSERT_RE.finditer(sql):
        table = m.group("table")
        cols = (
            [c.strip(" `\"'") for c in m.group("cols").split(",")]
            if m.group("cols") else []
        )
        for row_m in _ROW_RE.finditer(m.group("vals")):
            values = _split_sql_values(row_m.group(1))
            if not values:
                continue
            if cols and len(cols) == len(values):
                pairs = "; ".join(f"{c} is {v}" for c, v in zip(cols, values, strict=True) if v)
            else:
                pairs = "; ".join(v for v in values if v)
            if pairs:
                lines.append(f"In table {table}: {pairs}.")
    return "\n".join(lines)


def _split_sql_values(row: str) -> list[str]:
    """Split a VALUES tuple body on commas outside of quotes."""
    out: list[str] = []
    buf: list[str] = []
    in_str = False
    i = 0
    while i < len(row):
        ch = row[i]
        if ch == "'" and not (in_str and i + 1 < len(row) and row[i + 1] == "'"):
            in_str = not in_str
            buf.append(ch)
        elif ch == "'" and in_str:  # escaped '' inside a string
            buf.append("'")
            i += 1
        elif ch == "," and not in_str:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        out.append("".join(buf).strip())
    cleaned = []
    for v in out:
        v = v.strip()
        if v.upper() == "NULL":
            cleaned.append("")
        elif len(v) >= 2 and v[0] == "'" and v[-1] == "'":
            cleaned.append(v[1:-1].replace("''", "'"))
        else:
            cleaned.append(v)
    return cleaned


def extract_text(filename: str, data: bytes) -> str:
    """Best-effort plain text from an uploaded document."""
    name = filename.lower()
    ext = name[name.rfind("."):] if "." in name else ""

    if ext == ".sql":
        raw = data.decode("utf-8", errors="replace")
        parsed = sql_dump_to_text(raw)
        # Fall back to raw text if the dump had no parseable INSERT rows
        # (e.g. schema-only), so schema comments are still indexable.
        return parsed if len(parsed) >= 40 else raw

    if ext in _TEXT_EXTENSIONS:
        return data.decode("utf-8", errors="replace")

    if ext == ".pdf":
        try:
            from io import BytesIO

            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError(
                'PDF support requires the documents extra: pip install ".[documents]"'
            ) from exc
        reader = PdfReader(BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    if ext == ".docx":
        try:
            from io import BytesIO

            from docx import Document
        except ImportError as exc:
            raise ValueError(
                'DOCX support requires the documents extra: pip install ".[documents]"'
            ) from exc
        doc = Document(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)

    raise ValueError(
        f"Unsupported file type {ext or '(none)'}. "
        "Supported: .txt .md .csv .html .json .sql .pdf .docx"
    )


async def index_source(
    site_id: int, kind: str, title: str, text: str, settings: Settings
) -> dict:
    """Chunk, embed, and store one source. Returns the source record."""
    text = text.strip()
    if not text:
        raise ValueError("The source contains no extractable text.")

    ref = "source://" + secrets.token_hex(10)
    page = Page(url=ref, title=title or kind, text=text)
    chunks = chunk_page(page, settings)
    if not chunks:
        raise ValueError("The source produced no indexable chunks.")

    vectors = await embed_texts([c.content for c in chunks], settings)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        from pgvector.asyncpg import Vector

        await conn.executemany(
            "INSERT INTO chunks (site_id, url, title, content, token_count, embedding) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            [
                (site_id, c.url, c.title, c.content, c.token_count, Vector(v))
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )
        source_id = await conn.fetchval(
            "INSERT INTO sources (site_id, kind, title, ref, chars) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            site_id, kind, title, ref, len(text),
        )
        await conn.execute(
            "UPDATE sites SET chunks_indexed = "
            "(SELECT count(*) FROM chunks WHERE site_id = $1) WHERE id = $1",
            site_id,
        )
    await store.invalidate_cache(site_id)
    return {"id": int(source_id), "kind": kind, "title": title, "ref": ref,
            "chars": len(text), "chunks": len(chunks)}


def qa_to_text(question: str, answer: str) -> str:
    """Render a Q&A pair as retrievable text."""
    return f"Q: {question.strip()}\nA: {answer.strip()}"
