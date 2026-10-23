"""Corrections (B5, ADR-0010 §3 and §6, ADR-0013 → Correction interaction).

Applying a correction to revision r is ONE transaction: correction row; revision r+1 with the corrected
span verified and the edit map; verified spans, the active ReadingState and every page read of the page in an
open cycle re-tokenised in place; every miscue of
the page (any revision) with status candidate/unsure/confirmed whose span maps onto the corrected span →
invalidated(page_text_corrected); Difficulties recomputed; lexicon updated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.study import knowledge, lexicon, miscues, pages
from leafi.study.alignment import ReadingState


class StaleRevision(RuntimeError):
    pass


@dataclass
class CorrectionResult:
    correction_id: int
    revision_id: int | None
    invalidated: list[int]
    state: ReadingState | None


def locate(text: str, old_text: str, near: int | None = None, window: tuple[int, int] | None = None
           ) -> tuple[int, int] | None:
    """Nearest whole-word, case-insensitive occurrence of `old_text` to `near`, inside `window` if given."""
    if not old_text.strip():
        return None
    pat = re.compile(r"(?<!\w)" + re.escape(old_text.strip()) + r"(?!\w)", re.IGNORECASE)
    hits = [(m.start(), m.end()) for m in pat.finditer(text)]
    if window is not None:
        hits = [h for h in hits if window[0] <= h[0] and h[1] <= window[1]]
    if not hits:
        return None
    if near is None:
        return hits[0] if len(hits) == 1 else None
    return min(hits, key=lambda h: (abs(h[0] - near), h[0]))


def retokenize(state: ReadingState, old_text: str, new_text: str, edits: list[pages.Edit],
               edited: tuple[int, int], revision_id: int) -> ReadingState:
    """Re-tokenise a page read's ReadingState on the new revision in place (ADR-0013 → Correction interaction).

    Untouched tokens carry status, `miscue_id`, `created_by` and `supplied`; a touched token (its span overlaps
    the edit) loses them and becomes `unread` behind the mapped `ccur` (the learner read the old text there) or
    `unattempted` at or after it. Only `unattempted` touched tokens pull `pcur` back or reopen a sentence.
    """
    new = ReadingState.from_text(new_text, page_read_id=state.page_read_id, revision_id=revision_id)
    by_span = {}
    for t in state.tokens:
        if not any(pages.overlaps(t.span, (e[0], e[1])) for e in edits):
            by_span[pages.map_span(t.span, edits)] = t
    touched: list[int] = []
    for i, t in enumerate(new.tokens):
        old = None if pages.overlaps(t.span, edited) else by_span.get(t.span)
        if old is None:
            touched.append(i)
            continue
        t.status, t.created_by, t.miscue_id, t.supplied = old.status, old.created_by, old.miscue_id, old.supplied

    def map_cursor(c: int) -> int:
        pos = state.tokens[c].start if c < state.n else len(old_text)
        npos = pages.map_point(pos, edits, "start")
        return next((i for i, t in enumerate(new.tokens) if t.start >= npos), new.n)

    new.ccur = map_cursor(state.ccur)
    new.pcur = max(new.ccur, map_cursor(state.pcur))
    reopened = {i for i in touched if i >= new.ccur}
    for i in touched:
        new.tokens[i].status = "unattempted" if i in reopened else "unread"
    if reopened:
        new.pcur = min(new.pcur, min(reopened))

    old_sent_of = {pages.map_span(t.span, edits): t.sentence_id for t in state.tokens}
    for sid in new.sentence_ids():
        idx = range(new.first_index(sid), new.last_index(sid) + 1)
        if any(i in reopened for i in idx):
            continue
        kept = [i for i in idx if i not in touched]
        if kept:
            done = all(old_sent_of.get(new.tokens[i].span) in state.completed for i in kept)
        else:  # every token replaced, all behind the frontier
            done = idx[-1] < new.ccur
        if done:
            new.completed.add(sid)
    new.turn_id = state.turn_id + 1
    return new


def _open_cycle_reads(store: Store, page_id: int, revision_id: int, skip: int | None) -> list[tuple[int, dict]]:
    """Page reads of the page whose cycle is open, at the revision being corrected (ADR-0013)."""
    rows = store.all("SELECT pr.id, pr.reading_state FROM page_reads pr JOIN cycles c ON c.id = pr.cycle_id "
                     "WHERE pr.page_id=? AND pr.page_revision_id=? AND c.status='open' "
                     "AND pr.reading_state IS NOT NULL ORDER BY pr.id", (page_id, revision_id))
    return [(r["id"], loads(r["reading_state"])) for r in rows if r["id"] != skip]


def _source_learner(source: str, learner_id: int | None) -> int | None:
    """Who made a correction (ADR-0018 §3): required unless the parent made it."""
    if source != "parent" and learner_id is None:
        raise ValueError(f"a {source} correction needs the learner who made it")
    return None if source == "parent" else learner_id


def apply_correction(store: Store, *, page_id: int, revision_id: int, char_start: int, char_end: int,
                     new_text: str, source: str, learner_id: int | None, utterance_id: int | None = None,
                     state: ReadingState | None = None, book_id: int | None = None) -> CorrectionResult:
    """The new revision is shared book text at once (ADR-0018 §3); the row records which learner made it."""
    by = _source_learner(source, learner_id)
    with store.transaction():
        cur = pages.current_revision(store, page_id)
        if cur is None or cur.id != revision_id:
            raise StaleRevision(f"page {page_id}: correction against revision {revision_id}, current is "
                                f"{cur.id if cur else None}")
        old_seg = cur.text[char_start:char_end]
        corr_id = store.insert("corrections", page_revision_id=cur.id, char_start=char_start, char_end=char_end,
                               old_text=old_seg, new_text=new_text, source=source, utterance_id=utterance_id,
                               source_learner_id=by, created_at=now_iso())
        text = cur.text[:char_start] + new_text + cur.text[char_end:]
        edits = [[char_start, char_end, char_start, char_start + len(new_text)]]
        edited_new = (char_start, char_start + len(new_text))
        verified = pages.transform_verified(cur.spans_verified, edits) + [list(edited_new)]
        new_rev = pages.insert_revision(store, page_id, text, "correction", verified, edits)

        def save(page_read_id: int, st: ReadingState) -> None:
            store.execute("UPDATE page_reads SET page_revision_id=?, reading_state=? WHERE id=?",
                          (new_rev, dumps(st.to_json()), page_read_id))

        new_state = None
        if state is not None:
            new_state = retokenize(state, cur.text, text, edits, edited_new, new_rev)
            if state.page_read_id is not None:
                save(state.page_read_id, new_state)
        for read_id, data in _open_cycle_reads(store, page_id, cur.id, state.page_read_id if state else None):
            other = ReadingState.from_json(cur.text, data)
            other.page_read_id = read_id
            save(read_id, retokenize(other, cur.text, text, edits, edited_new, new_rev))

        revs = {r.id: r.rev for r in pages.chain(store, page_id)}
        invalidated: list[int] = []
        for m in store.all(
            "SELECT m.id, m.page_revision_id, m.expected_char_span FROM miscues m "
            "JOIN page_revisions pr ON pr.id = m.page_revision_id "
            "WHERE pr.page_id=? AND m.status IN ('candidate','unsure','confirmed')", (page_id,)):
            span = tuple(loads(m["expected_char_span"]))
            mapped = pages.map_to_revision(store, page_id, span, revs[m["page_revision_id"]], cur.rev)
            if pages.overlaps(mapped, (char_start, char_end)):
                miscues.set_status(store, m["id"], "invalidated", reason="page_text_corrected")
                invalidated.append(m["id"])
        knowledge.recompute_difficulties(store, None)  # the page is shared: any learner's miscues may have moved
        if book_id is None:
            book_id = store.one("SELECT book_id FROM pages WHERE id=?", (page_id,))["book_id"]
        lexicon.add_correction(store, book_id, new_text)
    return CorrectionResult(corr_id, new_rev, invalidated, new_state)


def record_unlocated(store: Store, *, revision_id: int, old_text: str, new_text: str, source: str,
                     learner_id: int | None, utterance_id: int | None = None) -> int:
    """A correction Leafi could not place: kept for the parent with `char_start = null`, no new revision."""
    return store.insert("corrections", page_revision_id=revision_id, char_start=None, char_end=None,
                        old_text=old_text, new_text=new_text, source=source, utterance_id=utterance_id,
                        source_learner_id=_source_learner(source, learner_id), created_at=now_iso())
