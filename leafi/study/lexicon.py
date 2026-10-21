"""Lexicon: words of the learner's books and corrections (ADR-0006 loop 2). Advisory in v1 (ADR-0011):
OCR snapping only proposes candidates and ASR hotwords stay off until measured.
"""

from __future__ import annotations

from collections import Counter

from rapidfuzz.distance import Levenshtein

from leafi.core.storage import Store, now_iso
from leafi.core.text import norm, words

CORRECTION_WEIGHT = 2.0


def _upsert(store: Store, word: str, language: str, source: str, book_id: int | None, weight: float) -> None:
    store.execute(
        "INSERT INTO lexicon(word, language, source, book_id, weight, updated_at) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(word, language, source, IFNULL(book_id, -1)) DO UPDATE SET weight=excluded.weight, "
        "updated_at=excluded.updated_at",
        (word, language, source, book_id, weight, now_iso()))


def rebuild(store: Store, book_id: int, language: str = "en") -> int:
    """Recompute `book` and `correction` rows of one book from current revisions + corrections.

    Manual rows survive. Returns the number of distinct words.
    """
    with store.transaction():
        store.execute("DELETE FROM lexicon WHERE book_id=? AND source IN ('book','correction')", (book_id,))
        book_words: Counter[str] = Counter()
        for r in store.all(
            "SELECT pr.text FROM page_revisions pr JOIN pages p ON p.id = pr.page_id WHERE p.book_id=? "
            "AND pr.rev = (SELECT MAX(rev) FROM page_revisions WHERE page_id = pr.page_id)", (book_id,)):
            book_words.update(w for w in (norm(x) for x in words(r["text"])) if w)
        corr_words: Counter[str] = Counter()
        for r in store.all(
            "SELECT c.new_text FROM corrections c JOIN page_revisions pr ON pr.id = c.page_revision_id "
            "JOIN pages p ON p.id = pr.page_id WHERE p.book_id=?", (book_id,)):
            corr_words.update(w for w in (norm(x) for x in words(r["new_text"])) if w)
        for w, c in book_words.items():
            _upsert(store, w, language, "book", book_id, float(c))
        for w, c in corr_words.items():
            _upsert(store, w, language, "correction", book_id, CORRECTION_WEIGHT * c)
    return len(set(book_words) | set(corr_words))


def add_correction(store: Store, book_id: int, new_text: str, language: str = "en") -> None:
    """Called inside the correction transaction (ADR-0010 §3)."""
    for w in {norm(x) for x in words(new_text)} - {""}:
        row = store.one("SELECT weight FROM lexicon WHERE word=? AND language=? AND source='correction' "
                        "AND book_id=?", (w, language, book_id))
        _upsert(store, w, language, "correction", book_id, (row["weight"] if row else 0.0) + CORRECTION_WEIGHT)


def add_manual(store: Store, word: str, language: str = "en") -> None:
    _upsert(store, norm(word), language, "manual", None, 1.0)


def entries(store: Store, book_id: int | None = None, language: str = "en") -> set[str]:
    if book_id is None:
        rows = store.all("SELECT DISTINCT word FROM lexicon WHERE language=?", (language,))
    else:
        rows = store.all("SELECT DISTINCT word FROM lexicon WHERE language=? AND (book_id=? OR book_id IS NULL)",
                         (language, book_id))
    return {r["word"] for r in rows}


SNAP_MODES = ("off", "advisory", "auto")  # OCR_SNAP values; only "off" changes behaviour here, "auto" is gated


def snap_candidates(store: Store, word: str, ocr_confidence: float | None, min_confidence: float,
                    book_id: int | None = None, mode: str = "advisory") -> list[str]:
    """OCR post-correction candidates within one edit, only when OCR confidence is low. Never applied
    automatically in v1 (`OCR_SNAP=advisory`); `off` returns nothing."""
    if mode == "off" or (ocr_confidence is not None and ocr_confidence >= min_confidence):
        return []
    w = norm(word)
    if not w:
        return []
    known = entries(store, book_id)
    if w in known:
        return []
    return sorted(k for k in known if Levenshtein.distance(w, k) == 1)


def hotwords(store: Store, book_id: int, mode: str) -> list[str] | None:
    """ASR biasing list; None while `ASR_HOTWORDS=off` (ADR-0011)."""
    if mode != "lexicon":
        return None
    return sorted(entries(store, book_id))
