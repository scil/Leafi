"""Books (B1): create/find by title or ISBN; identify from the camera (barcode → catalog, else cover OCR
title, else ask the learner). Catalog lookups send ISBN digits only (ADR-0011).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from leafi.core.storage import Store, now_iso

ISBN_RE = re.compile(r"^(97[89])?\d{9}[\dX]$")


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "book"


def normalize_isbn(raw: str) -> str | None:
    digits = re.sub(r"[^0-9X]", "", raw.upper())
    return digits if ISBN_RE.match(digits) else None


def find_by_title(store: Store, title: str, threshold: float = 0.85) -> int | None:
    best = None
    for r in store.all("SELECT id, title FROM books WHERE archived_at IS NULL"):
        s = fuzz.ratio(r["title"].lower(), title.lower()) / 100.0
        if s >= threshold and (best is None or s > best[0]):
            best = (s, r["id"])
    return best[1] if best else None


def find_or_create(store: Store, title: str, isbn: str | None = None, language: str = "en") -> int:
    if isbn:
        r = store.one("SELECT id FROM books WHERE isbn=? AND archived_at IS NULL", (isbn,))
        if r:
            return r["id"]
    found = find_by_title(store, title)
    if found:
        return found
    return store.insert("books", title=title.strip(), isbn=isbn, language=language, created_at=now_iso())


def title_of(store: Store, book_id: int) -> str:
    return store.one("SELECT title FROM books WHERE id=?", (book_id,))["title"]


@dataclass(frozen=True)
class BookGuess:
    source: str  # barcode | cover | none
    title: str | None
    isbn: str | None


async def identify(eye, ocr, catalog, *, max_width: int = 1920) -> BookGuess:
    """Camera identification; the session confirms the guess with the learner before using it."""
    if eye is None or ocr is None:
        return BookGuess("none", None, None)
    frame = await eye.snapshot(max_width)
    if frame is None:
        return BookGuess("none", None, None)
    for code in await ocr.barcodes(frame):
        isbn = normalize_isbn(code)
        if isbn:
            title = await catalog.title_for_isbn(isbn) if catalog is not None else None
            return BookGuess("barcode", title, isbn)
    result = await ocr.read(frame)
    lines = sorted((ln for ln in result.lines if ln.text.strip()), key=lambda ln: -ln.height)
    if lines and result.confidence >= 0.5:
        return BookGuess("cover", lines[0].text.strip(), None)
    return BookGuess("none", None, None)
