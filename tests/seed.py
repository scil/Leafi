"""Small builders for temp-SQLite tests (real storage, never mocked)."""

from __future__ import annotations

import datetime as dt

from leafi.core.storage import Store, now_iso
from leafi.core.text import tokenize
from leafi.study import books, miscues, pages


def book_page(store: Store, text: str, *, title: str = "Fixture", source: str = "ocr", number: int | None = 1):
    book_id = books.find_or_create(store, title)
    page_id = pages.create_page(store, book_id, number, pages.observations_of(text))
    if source == "manual":
        rev = pages.add_manual_revision(store, page_id, text)
    else:
        rev = pages.insert_revision(store, page_id, text, "ocr", [], [], "mock", 0.9)
    return book_id, page_id, rev


def session(store: Store, book_id: int, *, days_ago: float = 0.0) -> int:
    started = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)).isoformat()
    return store.insert("reading_sessions", book_id=book_id, started_at=started, mode="text")


def page_read(store: Store, session_id: int, page_id: int, rev: int) -> int:
    return store.insert("page_reads", session_id=session_id, page_id=page_id, page_revision_id=rev,
                        started_at=now_iso())


def miscue(store: Store, read_id: int, rev: int, text: str, word: str, status: str = "candidate",
           reason: str | None = None, heard: str | None = "x") -> int:
    toks = tokenize(text)
    idx = next(i for i, t in enumerate(toks) if t.text == word)
    mid = miscues.create(store, observation_id=None, page_read_id=read_id, revision_id=rev, expected=word,
                         token_index=idx, char_span=(toks[idx].start, toks[idx].end), heard=heard)
    if status != "candidate":
        miscues.set_status(store, mid, status, reason=reason,
                           evidence="acoustic" if status == "confirmed" else None)
    return mid


def status_of(store: Store, miscue_id: int) -> tuple[str, str | None]:
    r = store.one("SELECT status, CASE status WHEN 'withdrawn' THEN withdrawn_reason WHEN 'unsure' THEN "
                  "unsure_reason WHEN 'invalidated' THEN invalidated_reason END AS reason FROM miscues WHERE id=?",
                  (miscue_id,))
    return r["status"], r["reason"]
