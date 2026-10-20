"""Session records: stale-session close (ADR-0013 → Interrupted session), summaries, export and the two
sanctioned deletions (ADR-0010 §9). Exports carry counts and items, never learner free text or audio.
"""

from __future__ import annotations

import logging
from pathlib import Path

from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.study import knowledge, miscues
from leafi.study.alignment import ReadingState

log = logging.getLogger("leafi.records")


def close_stale_sessions(store: Store) -> list[int]:
    """Sessions with `ended_at` null: open candidates → unsure(interrupted), tokens settled, state kept."""
    closed = []
    for s in store.all("SELECT id FROM reading_sessions WHERE ended_at IS NULL"):
        with store.transaction():
            for pr in store.all("SELECT pr.id, pr.reading_state, rev.text FROM page_reads pr "
                                "JOIN page_revisions rev ON rev.id = pr.page_revision_id WHERE pr.session_id=?",
                                (s["id"],)):
                miscues.settle_open(store, pr["id"], "interrupted")
                if pr["reading_state"]:
                    st = ReadingState.from_json(pr["text"], loads(pr["reading_state"]))
                    for t in st.tokens:
                        if t.status == "candidate":
                            t.status = "settled"
                    store.execute("UPDATE page_reads SET reading_state=? WHERE id=?", (dumps(st.to_json()), pr["id"]))
            summ = summary(store, s["id"])
            summ["interrupted"] = True
            store.execute("UPDATE reading_sessions SET ended_at=?, summary=? WHERE id=?",
                          (now_iso(), dumps(summ), s["id"]))
            knowledge.recompute_difficulties(store)
        closed.append(s["id"])
    return closed


def resumable_read(store: Store, book_id: int):
    """Latest page read of an interrupted session of this book that is worth continuing, or None."""
    for r in store.all(
        "SELECT pr.*, s.summary FROM page_reads pr JOIN reading_sessions s ON s.id = pr.session_id "
        "WHERE s.book_id=? AND s.ended_at IS NOT NULL ORDER BY pr.id DESC LIMIT 1", (book_id,)):
        if not loads(r["summary"], {}).get("interrupted") or not r["reading_state"]:
            return None
        cur = store.one("SELECT id, text FROM page_revisions WHERE page_id=? ORDER BY rev DESC LIMIT 1",
                        (r["page_id"],))
        if cur["id"] != r["page_revision_id"]:
            return None
        st = ReadingState.from_json(cur["text"], loads(r["reading_state"]))
        if st.ccur == 0 or st.page_complete():
            return None
        return r
    return None


def summary(store: Store, session_id: int) -> dict:
    reads = store.all("SELECT * FROM page_reads WHERE session_id=?", (session_id,))
    rid = [r["id"] for r in reads]
    marks = ",".join("?" * len(rid)) or "NULL"
    counts = {row["status"]: row["n"] for row in store.all(
        f"SELECT status, COUNT(*) AS n FROM miscues WHERE page_read_id IN ({marks}) GROUP BY status", tuple(rid))}
    practices = store.one(
        f"SELECT COUNT(*) AS n FROM practices p JOIN miscues m ON m.id = p.miscue_id WHERE m.page_read_id IN ({marks})",
        tuple(rid))["n"]
    items = store.one("SELECT COUNT(DISTINCT knowledge_item_id) AS n FROM encounters WHERE session_id=?",
                      (session_id,))["n"]
    return {
        "pages": len({r["page_id"] for r in reads}),
        "page_reads": len(reads),
        "tokens_expected": sum(r["tokens_expected"] for r in reads),
        "tokens_committed": sum(r["tokens_committed"] for r in reads),
        "tokens_matched": sum(r["tokens_matched"] for r in reads),
        "tokens_unread": sum(r["tokens_unread"] for r in reads),
        "candidates": sum(counts.values()),
        "confirmed": counts.get("confirmed", 0),
        "withdrawn": counts.get("withdrawn", 0),
        "unsure": counts.get("unsure", 0),
        "invalidated": counts.get("invalidated", 0),
        "open": counts.get("candidate", 0),
        "practices": practices,
        "items_learned": items,
    }


def export_session(store: Store, session_id: int) -> dict:
    s = store.one("SELECT * FROM reading_sessions WHERE id=?", (session_id,))
    if s is None:
        raise LookupError(f"session {session_id}")
    book = store.one("SELECT title FROM books WHERE id=?", (s["book_id"],)) if s["book_id"] else None
    pages_out = [dict(page_id=r["page_id"], printed_number=r["printed_number"], revision=r["rev"],
                      attempt=r["attempt"], tokens_expected=r["tokens_expected"],
                      tokens_committed=r["tokens_committed"], tokens_unread=r["tokens_unread"])
                 for r in store.all("SELECT pr.*, p.printed_number, rev.rev FROM page_reads pr JOIN pages p ON "
                                    "p.id = pr.page_id JOIN page_revisions rev ON rev.id = pr.page_revision_id "
                                    "WHERE pr.session_id=?", (session_id,))]
    miscue_out = [dict(expected=r["expected"], status=r["status"], evidence=r["evidence"],
                       reason=r["withdrawn_reason"] or r["unsure_reason"] or r["invalidated_reason"])
                  for r in store.all("SELECT m.* FROM miscues m JOIN page_reads pr ON pr.id = m.page_read_id "
                                     "WHERE pr.session_id=?", (session_id,))]
    items = [dict(kind=r["kind"], key=r["key"], status=r["status"], explanation_en=r["explanation_en"])
             for r in store.all("SELECT DISTINCT k.kind, k.key, k.status, e.explanation_en FROM encounters e "
                                "JOIN knowledge_items k ON k.id = e.knowledge_item_id WHERE e.session_id=?",
                                (session_id,))]
    return {"session": session_id, "book": book["title"] if book else None, "mode": s["mode"],
            "started_at": s["started_at"], "ended_at": s["ended_at"], "summary": loads(s["summary"], {}),
            "pages": pages_out, "miscues": miscue_out, "knowledge_items": items}


def forget_session(store: Store, session_id: int) -> None:
    """Delete the session's utterances, observations, practices and miscues; keep the summary counts."""
    with store.transaction():
        reads = [r["id"] for r in store.all("SELECT id FROM page_reads WHERE session_id=?", (session_id,))]
        marks = ",".join("?" * len(reads)) or "NULL"
        utt = [r["id"] for r in store.all(
            f"SELECT id FROM utterances WHERE session_id=? OR page_read_id IN ({marks})", (session_id, *reads))]
        umarks = ",".join("?" * len(utt)) or "NULL"
        store.execute(f"UPDATE corrections SET utterance_id=NULL WHERE utterance_id IN ({umarks})", tuple(utt))
        store.execute(f"DELETE FROM practices WHERE miscue_id IN (SELECT id FROM miscues WHERE page_read_id IN "
                      f"({marks}))", tuple(reads))
        store.execute(f"DELETE FROM miscues WHERE page_read_id IN ({marks})", tuple(reads))
        store.execute(f"DELETE FROM observations WHERE utterance_id IN ({umarks})", tuple(utt))
        store.execute(f"DELETE FROM utterances WHERE id IN ({umarks})", tuple(utt))
        knowledge.recompute_difficulties(store)


def forget_book(store: Store, book_id: int) -> None:
    sessions = [r["id"] for r in store.all("SELECT id FROM reading_sessions WHERE book_id=?", (book_id,))]
    for sid in sessions:
        forget_session(store, sid)
    with store.transaction():
        page_ids = [r["id"] for r in store.all("SELECT id FROM pages WHERE book_id=?", (book_id,))]
        pm = ",".join("?" * len(page_ids)) or "NULL"
        rev_ids = [r["id"] for r in store.all(f"SELECT id FROM page_revisions WHERE page_id IN ({pm})",
                                              tuple(page_ids))]
        rm = ",".join("?" * len(rev_ids)) or "NULL"
        sm = ",".join("?" * len(sessions)) or "NULL"
        for img in store.all(f"SELECT path FROM page_images WHERE page_id IN ({pm})", tuple(page_ids)):
            try:
                Path(img["path"]).unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete a page image file")
        store.execute(f"DELETE FROM page_images WHERE page_id IN ({pm})", tuple(page_ids))
        store.execute(f"DELETE FROM encounters WHERE page_revision_id IN ({rm}) OR session_id IN ({sm})",
                      (*rev_ids, *sessions))
        store.execute(f"DELETE FROM page_reads WHERE session_id IN ({sm}) OR page_id IN ({pm})",
                      (*sessions, *page_ids))
        store.execute(f"DELETE FROM corrections WHERE page_revision_id IN ({rm})", tuple(rev_ids))
        store.execute(f"DELETE FROM page_revisions WHERE id IN ({rm})", tuple(rev_ids))
        store.execute(f"DELETE FROM pages WHERE id IN ({pm})", tuple(page_ids))
        store.execute("DELETE FROM lexicon WHERE book_id=?", (book_id,))
        store.execute("UPDATE books SET archived_at=? WHERE id=?", (now_iso(), book_id))
        knowledge.recompute_difficulties(store)
