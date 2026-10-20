"""Pages and immutable page revisions (ADR-0010). Page text is read only through `current_text()`.

Spans are half-open code-point offsets; an edit map is a list of `[old_start, old_end, new_start, new_end]`
from the parent revision, sorted and non-overlapping. A later OCR never overwrites verified spans.
"""

from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.core.text import TOKENIZER_VERSION, words

Edit = list[int]  # [old_start, old_end, new_start, new_end]
MATCH_CONFIDENT = 0.9
MATCH_MARGIN = 0.05
MATCH_NEW_BELOW = 0.75  # count terms alone give unrelated pages ~0.3; first/last lines must agree


# ---------------------------------------------------------------- spans and edit maps


def map_point(p: int, edits: list[Edit], side: Literal["start", "end"] = "start") -> int:
    """Map a position through sorted edits. Inside an edited range: its new start (`start`) or end (`end`)."""
    for os_, oe, ns, ne in edits:
        if p <= os_:
            return p - os_ + ns
        if p < oe:
            return ns if side == "start" else ne
    if not edits:
        return p
    _, oe, _, ne = edits[-1]
    return p - oe + ne


def overlaps(span: tuple[int, int], edit_span: tuple[int, int]) -> bool:
    a, b = span
    s, e = edit_span
    if s == e:  # pure insertion point
        return a < s < b
    return a < e and s < b


def map_span(span: tuple[int, int], edits: list[Edit]) -> tuple[int, int]:
    a, b = span
    return map_point(a, edits, "start"), map_point(b, edits, "end")


def merge_spans(spans: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if a >= b:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def transform_verified(spans: list[list[int]], edits: list[Edit]) -> list[list[int]]:
    return merge_spans([list(map_span((a, b), edits)) for a, b in spans])


# ---------------------------------------------------------------- rows


@dataclass(frozen=True)
class Revision:
    id: int
    page_id: int
    rev: int
    text: str
    source: str
    spans_verified: list[list[int]]
    edit_map: list[Edit]
    tokenizer_version: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> Revision:
        return cls(r["id"], r["page_id"], r["rev"], r["text"], r["source"], loads(r["spans_verified"], []),
                   loads(r["edit_map"], []), r["tokenizer_version"])


def create_page(store: Store, book_id: int, printed_number: int | None = None,
                observations: dict | None = None) -> int:
    return store.insert("pages", book_id=book_id, printed_number=printed_number,
                        observations=dumps(observations) if observations else None, created_at=now_iso())


def insert_revision(store: Store, page_id: int, text: str, source: str, spans_verified: list[list[int]],
                    edit_map: list[Edit], ocr_backend: str | None = None,
                    ocr_confidence: float | None = None) -> int:
    row = store.one("SELECT MAX(rev) AS r FROM page_revisions WHERE page_id=?", (page_id,))
    rev = (row["r"] or 0) + 1
    return store.insert("page_revisions", page_id=page_id, rev=rev, text=text, source=source,
                        spans_verified=dumps(merge_spans(spans_verified)), edit_map=dumps(edit_map),
                        tokenizer_version=TOKENIZER_VERSION, ocr_backend=ocr_backend,
                        ocr_confidence=ocr_confidence, created_at=now_iso())


def current_revision(store: Store, page_id: int) -> Revision | None:
    r = store.one("SELECT * FROM page_revisions WHERE page_id=? ORDER BY rev DESC LIMIT 1", (page_id,))
    return Revision.from_row(r) if r else None


def revision(store: Store, revision_id: int) -> Revision:
    r = store.one("SELECT * FROM page_revisions WHERE id=?", (revision_id,))
    if r is None:
        raise LookupError(f"revision {revision_id}")
    return Revision.from_row(r)


def current_text(store: Store, page_id: int) -> str | None:
    """Page text = the latest revision's text (corrected text wins over OCR, always)."""
    rev = current_revision(store, page_id)
    return rev.text if rev else None


def chain(store: Store, page_id: int) -> list[Revision]:
    return [Revision.from_row(r) for r in
            store.all("SELECT * FROM page_revisions WHERE page_id=? ORDER BY rev", (page_id,))]


def map_to_revision(store: Store, page_id: int, span: tuple[int, int], from_rev: int, to_rev: int
                    ) -> tuple[int, int]:
    """Map a span of revision `from_rev` forward through every edit map up to `to_rev`."""
    for r in chain(store, page_id):
        if from_rev < r.rev <= to_rev:
            span = map_span(span, r.edit_map)
    return span


def add_manual_revision(store: Store, page_id: int, text: str) -> int:
    """ADR-0010 §7: manual text is fully verified. Identical text to the current revision is reused."""
    cur = current_revision(store, page_id)
    if cur and cur.text == text:
        return cur.id
    edits = _diff_edits(cur.text, text) if cur else []
    return insert_revision(store, page_id, text, "manual", [[0, len(text)]], edits)


def _diff_edits(old: str, new: str) -> list[Edit]:
    edits = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            edits.append([i1, i2, j1, j2])
    return edits


def add_ocr_revision(store: Store, page_id: int, ocr_text: str, backend: str, confidence: float | None
                     ) -> int | None:
    """New OCR of a known page: unverified spans take the OCR text, verified spans keep theirs.

    Returns the new revision id, or None when nothing changed.
    """
    cur = current_revision(store, page_id)
    if cur is None:
        return insert_revision(store, page_id, ocr_text, "ocr", [], [], backend, confidence)
    verified = [tuple(s) for s in cur.spans_verified]
    out: list[str] = []
    edits: list[Edit] = []
    pos = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, cur.text, ocr_text, autojunk=False).get_opcodes():
        old_seg = cur.text[i1:i2]
        if tag == "equal" or any(overlaps((a, b), (i1, i2)) or (i1 == i2 and a <= i1 < b) for a, b in verified):
            out.append(old_seg)
            pos += len(old_seg)
            continue
        new_seg = ocr_text[j1:j2]
        edits.append([i1, i2, pos, pos + len(new_seg)])
        out.append(new_seg)
        pos += len(new_seg)
    text = "".join(out)
    if text == cur.text:
        return None
    return insert_revision(store, page_id, text, "ocr", transform_verified(cur.spans_verified, edits), edits,
                           backend, confidence)


# ---------------------------------------------------------------- identity (ADR-0010 §1)


def observations_of(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return {"first_line": lines[0] if lines else "", "last_line": lines[-1] if lines else "",
            "word_count": len(words(text)), "line_count": len(lines)}


def observation_score(a: dict, b: dict) -> float:
    def ratio(x: str, y: str) -> float:
        return fuzz.ratio(x, y) / 100.0

    def closeness(x: int, y: int) -> float:
        return 1.0 - abs(x - y) / max(x, y, 1)

    return (0.35 * ratio(a["first_line"], b["first_line"]) + 0.35 * ratio(a["last_line"], b["last_line"])
            + 0.2 * closeness(a["word_count"], b["word_count"]) + 0.1 * closeness(a["line_count"], b["line_count"]))


@dataclass(frozen=True)
class PageMatch:
    status: Literal["matched", "uncertain", "new"]
    page_id: int | None
    score: float
    candidates: tuple[int, ...] = ()


def match_page(store: Store, book_id: int, observations: dict, printed_number: int | None = None) -> PageMatch:
    """`(book_id, printed_number)` when a number was read with confidence; else score the observation sets.

    Below `MATCH_CONFIDENT` (0.9) or two candidates within `MATCH_MARGIN` → uncertain; below
    `MATCH_NEW_BELOW` (0.75) for every stored page → a new page (plan Decision log).
    """
    if printed_number is not None:
        r = store.one("SELECT id FROM pages WHERE book_id=? AND printed_number=?", (book_id, printed_number))
        return PageMatch("matched", r["id"], 1.0) if r else PageMatch("new", None, 0.0)
    scored = []
    for r in store.all("SELECT id, observations FROM pages WHERE book_id=? AND observations IS NOT NULL",
                       (book_id,)):
        scored.append((observation_score(observations, loads(r["observations"])), r["id"]))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < MATCH_NEW_BELOW:
        return PageMatch("new", None, scored[0][0] if scored else 0.0)
    best, pid = scored[0]
    close = tuple(p for s, p in scored if best - s <= MATCH_MARGIN)
    if best < MATCH_CONFIDENT or len(close) > 1:
        return PageMatch("uncertain", pid, best, close)
    return PageMatch("matched", pid, best)


def confirm_observations(store: Store, page_id: int, observations: dict) -> None:
    store.execute("UPDATE pages SET observations=? WHERE id=?", (dumps(observations), page_id))
