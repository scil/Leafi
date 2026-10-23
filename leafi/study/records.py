"""Session records: stale-session close (ADR-0013 → Interrupted session), summaries, export and the sanctioned
deletions: `forget --session` / `--book` (ADR-0010 §9) and `forget --learner` (ADR-0018 §1). Exports carry counts
and items, never learner free text or audio.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.study import knowledge, miscues
from leafi.study.alignment import ReadingState

log = logging.getLogger("leafi.records")


def close_stale_sessions(store: Store) -> list[int]:
    """Sessions with `ended_at` null: open candidates → unsure(interrupted), tokens settled, state kept."""
    closed = []
    for s in store.all("SELECT id, learner_id FROM reading_sessions WHERE ended_at IS NULL"):
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
            knowledge.recompute_difficulties(store, s["learner_id"])
        closed.append(s["id"])
    return closed


def resumable_read(store: Store, learner_id: int, book_id: int):
    """Latest page read of this learner's interrupted session of this book worth continuing, or None
    ("continue from page N?" is keyed by learner and book, ADR-0018 §1)."""
    for r in store.all(
        "SELECT pr.*, s.summary FROM page_reads pr JOIN reading_sessions s ON s.id = pr.session_id "
        "WHERE s.learner_id=? AND s.book_id=? AND s.ended_at IS NOT NULL ORDER BY pr.id DESC LIMIT 1",
        (learner_id, book_id)):
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
    return {"session": session_id, "learner": s["learner_id"], "book": book["title"] if book else None,
            "mode": s["mode"],
            "started_at": s["started_at"], "ended_at": s["ended_at"], "summary": loads(s["summary"], {}),
            "pages": pages_out, "miscues": miscue_out, "knowledge_items": items}


def _marks(ids: list) -> str:
    return ",".join("?" * len(ids)) or "NULL"


def _delete_session_records(store: Store, session_id: int) -> None:
    """The session's evidence and the ADR-0017 §7.2 records reached through it, inside the caller's
    transaction; the session row and its page reads (summary counts) stay."""
    reads = [r["id"] for r in store.all("SELECT id FROM page_reads WHERE session_id=?", (session_id,))]
    marks = _marks(reads)
    utt = [r["id"] for r in store.all(
        f"SELECT id FROM utterances WHERE session_id=? OR page_read_id IN ({marks})", (session_id, *reads))]
    umarks = _marks(utt)
    acts = [r["id"] for r in store.all("SELECT id FROM activities WHERE session_id=?", (session_id,))]
    amarks = _marks(acts)
    store.execute(f"UPDATE corrections SET utterance_id=NULL WHERE utterance_id IN ({umarks})", tuple(utt))
    store.execute(f"DELETE FROM practices WHERE miscue_id IN (SELECT id FROM miscues WHERE page_read_id IN "
                  f"({marks}))", tuple(reads))
    store.execute(f"DELETE FROM miscues WHERE page_read_id IN ({marks})", tuple(reads))
    store.execute(f"DELETE FROM observations WHERE utterance_id IN ({umarks})", tuple(utt))
    store.execute(f"DELETE FROM utterances WHERE id IN ({umarks})", tuple(utt))
    # ADR-0018 §1: a note whose citations all point into this session goes (ADR-0017 §7.1); other notes lose
    # only the citations of this session's activities.
    store.execute(f"DELETE FROM learner_notes WHERE id IN (SELECT note_id FROM learner_note_citations GROUP BY "
                  f"note_id HAVING SUM(activity_id NOT IN ({amarks})) = 0)", tuple(acts))
    store.execute(f"DELETE FROM learner_note_citations WHERE activity_id IN ({amarks})", tuple(acts))
    store.execute(f"DELETE FROM retrieval_events WHERE activity_id IN ({amarks})", tuple(acts))
    store.execute("DELETE FROM brain_calls WHERE session_id=?", (session_id,))
    store.execute("DELETE FROM egress_log WHERE session_id=?", (session_id,))
    store.execute("UPDATE page_reads SET cycle_id=NULL WHERE session_id=?", (session_id,))
    store.execute("DELETE FROM activities WHERE session_id=?", (session_id,))
    store.execute("DELETE FROM cycles WHERE session_id=?", (session_id,))


def forget_session(store: Store, session_id: int) -> None:
    """Delete the session's utterances, observations, practices, miscues, activities, cycles, Brain calls,
    retrieval events and egress rows; keep the summary counts."""
    with store.transaction():
        _delete_session_records(store, session_id)
        learner = learner_store.session_learner(store, session_id)
        if learner is not None:
            knowledge.recompute_difficulties(store, learner)
    if not store.checkpoint():  # the -wal still holds the deleted rows' old pages until it is emptied (ADR-0019 §7)
        log.warning("forget: another connection is reading; the supervisor's periodic checkpoint retries")


def forget_book(store: Store, book_id: int) -> None:
    sessions = [r["id"] for r in store.all("SELECT id FROM reading_sessions WHERE book_id=?", (book_id,))]
    for sid in sessions:
        forget_session(store, sid)
    with store.transaction():
        store.execute("DELETE FROM book_notes WHERE book_id=?", (book_id,))
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
        knowledge.recompute_difficulties(store, None)
    if not store.checkpoint():
        log.warning("forget: another connection is reading; the supervisor's periodic checkpoint retries")


# ---------------------------------------------------------------- forget --learner (ADR-0018 §1)


class LearnerBusy(RuntimeError):
    """The learner owns a session that has not ended; forgetting waits until it has."""


@dataclass
class ForgetReport:
    learner_id: int
    sessions: int = 0
    derived_removed: int = 0
    anki_notes: list[int] = field(default_factory=list)  # cards already in Anki: the household removes them
    deck: str | None = None


# What a derived copy naming the forgotten learner becomes, per provenance column pair (§1 "every derived copy"):
# a row whose whole point is the text is deleted; a text beside other data is cleared to empty `system` text.
_CLEAR = {
    ("activities", "outcome_provenance_class"): "outcome=NULL",
    ("activities", "assessment_provenance_class"): "assessment=NULL",
    ("encounters", "explanation_provenance_class"): "explanation_en=NULL, explanation_zh=NULL, example=NULL",
    # another learner's utterance keeps its row (its observations, miscues and corrections point at it) and
    # loses its text (codex M3 #7)
    ("utterances", "provenance_class"): "text='', words='[]'",
}


def _remember_notes(store: Store, learner_id: int, note_ids: list[int]) -> None:
    """Cards already in Anki, kept on the marked learner row in the same transaction that deletes their outbox
    rows, so a forget stopped between batches still reports them at the end (codex M3 #8)."""
    if not note_ids:
        return
    row = learner_store.get(store, learner_id)
    settings = loads(row["settings"], {})
    settings["forget.anki_notes"] = sorted(set(settings.get("forget.anki_notes", [])) | set(note_ids))
    store.execute("UPDATE learners SET settings=? WHERE id=?", (dumps(settings), learner_id))


def _purge_derived(store: Store, learner_id: int, report: ForgetReport) -> None:
    """Every stored text, in any learner's rows, whose `source_learners` include the learner."""
    for table, cls_col, src_col in learner_store.PROVENANCE:
        where = f"EXISTS(SELECT 1 FROM json_each({table}.{src_col}) WHERE value = ?)"
        clear = _CLEAR.get((table, cls_col))
        if clear is not None:
            n = store.execute(f"UPDATE {table} SET {clear}, {cls_col}='system', {src_col}='[]' WHERE {where}",
                              (learner_id,)).rowcount
        else:
            if table == "anki_outbox":
                _remember_notes(store, learner_id, [r["anki_note_id"] for r in store.all(
                    f"SELECT anki_note_id FROM anki_outbox WHERE {where} AND anki_note_id IS NOT NULL",
                    (learner_id,))])
            n = store.execute(f"DELETE FROM {table} WHERE {where}", (learner_id,)).rowcount
        report.derived_removed += max(n, 0)


def forget_learner(store: Store, learner_id: int, data_dir: Path, anki_base_deck: str = "Leafi") -> ForgetReport:
    """`forget --learner`: mark, delete in small transactions, rescan, delete the row (ADR-0018 §1). Re-runnable:
    a run stopped half-way leaves the learner marked, and the next run carries on. The TTS-cache sidecars (M5)
    and `data/evals/decisions/` (M7) join the stores below when they exist."""
    from leafi.study.anki import deck_for

    report = ForgetReport(learner_id)
    row = learner_store.get(store, learner_id)
    if row is None:
        raise LookupError(f"no learner #{learner_id}")
    report.deck = deck_for(store, learner_id, anki_base_deck)
    with store.transaction():
        marked = store.execute(
            "UPDATE learners SET forgetting=1 WHERE id=? AND NOT EXISTS(SELECT 1 FROM reading_sessions WHERE "
            "learner_id=? AND ended_at IS NULL)", (learner_id, learner_id)).rowcount
        if not marked:
            raise LearnerBusy(f"learner #{learner_id} has a session that has not ended; stop it first")
        # The names move into household_terms first, so shared text (corrections) keeps them replaced (§3).
        store.execute("INSERT INTO household_terms(term, kind, former_learner_id, created_at) SELECT ?, 'name', ?, ? "
                      "WHERE NOT EXISTS(SELECT 1 FROM household_terms WHERE term = ? COLLATE NOCASE)",
                      (row["display_name"], learner_id, now_iso(), row["display_name"]))
    for s in store.all("SELECT id FROM reading_sessions WHERE learner_id=? ORDER BY id", (learner_id,)):
        with store.transaction():
            _delete_session_records(store, s["id"])
            reads = [r["id"] for r in store.all("SELECT id FROM page_reads WHERE session_id=?", (s["id"],))]
            store.execute(f"DELETE FROM utterances WHERE page_read_id IN ({_marks(reads)})", tuple(reads))
            store.execute("DELETE FROM encounters WHERE session_id=?", (s["id"],))
            store.execute("DELETE FROM learner_notes WHERE session_id=?", (s["id"],))
            store.execute("DELETE FROM book_notes WHERE session_id=?", (s["id"],))
            store.execute("DELETE FROM page_reads WHERE session_id=?", (s["id"],))
            store.execute("DELETE FROM reading_sessions WHERE id=?", (s["id"],))
        report.sessions += 1
    with store.transaction():
        _remember_notes(store, learner_id, [r["anki_note_id"] for r in store.all(
            "SELECT anki_note_id FROM anki_outbox WHERE learner_id=? AND anki_note_id IS NOT NULL", (learner_id,))])
        store.execute("DELETE FROM learner_note_citations WHERE note_id IN (SELECT id FROM learner_notes WHERE "
                      "learner_id=?)", (learner_id,))
        store.execute("DELETE FROM retrieval_events WHERE learner_id=?", (learner_id,))
        for table in ("learner_notes", "book_notes", "review_answers", "difficulties", "encounters", "anki_outbox",
                      "egress_log"):
            store.execute(f"DELETE FROM {table} WHERE learner_id=?", (learner_id,))
        store.execute("DELETE FROM retrieval_events WHERE item_id IN (SELECT id FROM knowledge_items WHERE "
                      "learner_id=?)", (learner_id,))
        store.execute("DELETE FROM knowledge_items WHERE learner_id=?", (learner_id,))
        # an egress row of another learner may name this learner's consent (codex M3 #6)
        store.execute("UPDATE egress_log SET consent_id=NULL WHERE consent_id IN (SELECT id FROM consents WHERE "
                      "learner_id=?)", (learner_id,))
        store.execute("DELETE FROM consents WHERE learner_id=?", (learner_id,))
        store.execute("UPDATE corrections SET utterance_id=NULL, source_learner_id=NULL, forgotten=1 "
                      "WHERE source_learner_id=?", (learner_id,))
    with store.transaction():
        _purge_derived(store, learner_id, report)
    folder = data_dir / "learners" / str(learner_id)
    if folder.exists():  # a failure (a file held open) raises and leaves the learner marked for a rerun (codex M3 #2)
        shutil.rmtree(folder)
    with store.transaction():  # the final rescan: a derived write that slipped in between the batches (§1)
        _purge_derived(store, learner_id, report)
        report.anki_notes = loads(learner_store.get(store, learner_id)["settings"], {}).get("forget.anki_notes", [])
        store.execute("DELETE FROM learners WHERE id=?", (learner_id,))
    if not store.checkpoint():
        log.warning("forget: another connection is reading; the supervisor's periodic checkpoint retries")
    return report
