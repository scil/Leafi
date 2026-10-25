"""What the Brain may write (ADR-0017 §7.1; M7 design D18): a decision's `records`, and the learner notes of
`extract_notes` after the session.

- `apply_records`: each record validated on its own (`assessment` ≤ 500 chars about a rendered activity of this
  session; `item_ignored` → an `ignore` event, the only status the Brain may ask for; `book_note` for the session's
  book), the valid ones written in one transaction while the epoch the observation was made under is still live.
  An invalid record or one the owner fence refuses is dropped and logged and never affects the decision.
- `extract_notes`: one `generate` call over the session's activities under the post-session context (its own call
  allowance `limits.extract_calls`, its own deadline, no ledger), skipped for guests; each note cites at least one
  activity the request rendered, else it is dropped.
- `current_notes`: what the observation's memory shows. A note leaves it once every activity it cites is more than
  `NOTES_SESSIONS` of the learner's sessions old and no newer note cites one of them (untuned).
"""

from __future__ import annotations

import logging
import time

from leafi.core import learner_store
from leafi.core.ports import Leaf, Section
from leafi.core.storage import loads, now_iso
from leafi.study import phrases
from leafi.study.brain import call as bc
from leafi.study.brain import prompts, schemas

log = logging.getLogger("leafi.brain.notes")

NOTES_SESSIONS = 10
NOTE_MAX = 200


def _bound(obs_ids: dict, rid: str, kind: str) -> int | None:
    hit = obs_ids.get(rid)
    return hit[1] if hit is not None and hit[0] == kind else None


def apply_records(s, w, records: list, obs_ids: dict, epoch) -> dict[str, int]:
    """Write the valid records; returns counts by kind, `dropped` included."""
    counts = {"assessment": 0, "item_ignored": 0, "book_note": 0, "dropped": 0}
    if not records:
        return counts
    if s.epoch() != epoch:  # D12: the observation is stale; nothing it implied is written
        counts["dropped"] = len(records)
        log.info("records dropped: the epoch moved on")
        return counts
    store, cfg = s.store, w.settings
    with store.transaction():
        for r in records:
            try:
                if isinstance(r, schemas.Assessment):
                    aid = _bound(obs_ids, r.activity_id, "activity")
                    row = store.one("SELECT id FROM activities WHERE id=? AND session_id=?", (aid, s.session_id)) \
                        if aid is not None else None
                    if row is None or not r.text.strip() or not phrases.safe(r.text):
                        raise ValueError("assessment")
                    learner_store.update_named(store, "activities", aid, assessment=r.text.strip())
                elif isinstance(r, schemas.ItemIgnored):
                    from leafi.study import item_status

                    item = _bound(obs_ids, r.item_id, "item")
                    if item is None or store.one("SELECT 1 FROM knowledge_items WHERE id=? AND learner_id=?",
                                                 (item, s.learner_id)) is None:
                        raise ValueError("item_ignored")
                    item_status.record(store, s.learner_id, item, "ignore", "brain", tz=cfg.household_tz,
                                       known_days=cfg.review_known_interval_days, session_id=s.session_id)
                elif isinstance(r, schemas.BookNote):
                    if w.book_id is None or not r.summary.strip() or not phrases.safe(r.summary):
                        raise ValueError("book_note")
                    learner_store.insert(store, "book_notes", s.learner_id, book_id=w.book_id,
                                         session_id=s.session_id, topic=r.topic.strip() or None,
                                         characters=r.characters.strip() or None, text=r.summary.strip(),
                                         created_at=now_iso())
                else:
                    raise ValueError(type(r).__name__)
                counts[r.kind] += 1
            except (ValueError, learner_store.LearnerUnavailable) as e:
                counts["dropped"] += 1
                log.info("record dropped: %s", e if isinstance(e, ValueError) else "learner unavailable")
    return counts


def current_notes(store, learner_id: int) -> list[tuple[int, str]]:
    """(id, text) of the notes the observation shows, oldest first."""
    recent = [r["id"] for r in store.all("SELECT id FROM reading_sessions WHERE learner_id=? ORDER BY id DESC "
                                         f"LIMIT {NOTES_SESSIONS}", (learner_id,))]
    marks = ",".join("?" * len(recent)) or "NULL"
    return [(r["id"], r["text"]) for r in store.all(
        "SELECT n.id, n.text FROM learner_notes n WHERE n.learner_id=? AND ("
        "EXISTS(SELECT 1 FROM learner_note_citations c JOIN activities a ON a.id = c.activity_id "
        f"WHERE c.note_id = n.id AND a.session_id IN ({marks})) OR "
        "EXISTS(SELECT 1 FROM learner_note_citations c JOIN learner_note_citations c2 ON c2.activity_id = "
        "c.activity_id JOIN learner_notes m ON m.id = c2.note_id WHERE c.note_id = n.id AND m.id > n.id AND "
        "m.learner_id = n.learner_id)) ORDER BY n.id", (learner_id, *recent))]


def _activity_leaves(store, session_id: int) -> tuple[list[Leaf], set[str]]:
    leaves, rendered = [], set()
    for r in store.all("SELECT id, kind, status, outcome FROM activities WHERE session_id=? ORDER BY id",
                       (session_id,)):
        rid = f"a{r['id']}"
        rendered.add(rid)
        counts = loads(r["outcome"], {}) if r["outcome"] else {}
        detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if isinstance(v, int | float | str))
        leaves.append(Leaf(f"{rid} {r['kind']} {r['status']}" + (f" ({detail})" if detail else "")))
    return leaves, rendered


def _notes_check(value: schemas.NotesContent, rendered: set[str]) -> list[tuple[str, list[int]]]:
    out = []
    for n in value.notes:
        cited = [int(a[1:]) for a in dict.fromkeys(n.activity_ids) if a in rendered]
        text = n.text.strip()
        if cited and text and len(text) <= NOTE_MAX and phrases.safe(text):
            out.append((text, cited))
    return out


async def extract_notes(s, w, env, summ: dict, *, deadline_s: float) -> None:
    """§7.1's post-session call; writes `summ["notes"]`: `skipped`, `unavailable` or the count written."""
    from leafi.study.brain import generate

    store = s.store
    kind = (learner_store.get(store, s.learner_id) or {"kind": "guest"})["kind"]
    if kind != "learner" or s.brain is None:
        summ["notes"] = "skipped"
        return
    leaves, rendered = _activity_leaves(store, s.session_id)
    if not leaves:
        summ["notes"] = "skipped"
        return
    allowance = bc.CallCountBudget(int(s.settings["limits.extract_calls"]))
    ctx = bc.CallContext(store=store, session_id=s.session_id, learner_id=s.learner_id,
                         deadline=time.monotonic() + deadline_s, budget_for=lambda tier: allowance,
                         prompt_version=prompts.PROMPT_VERSION, pending_audit=s.pending_audit_brain)
    sections = (generate.learner_context(s), Section("activities", tuple(leaves)))
    make = prompts.generate_request("notes", sections, schemas.NotesContent, policy=prompts.policy_text(
        autonomy=s.autonomy, age_band=None), learner_id=s.learner_id, session_id=s.session_id)
    result = await bc.brain_call(s.brain, ctx, "generate", make, schemas.NotesContent.model_validate)
    while s.pending_audit_brain:  # after finalize nothing else flushes them
        bc._insert(store, s.pending_audit_brain.pop(0))
    if result is None:
        summ["notes"] = "unavailable"
        return
    written = 0
    for text, cited in _notes_check(result.value, rendered):
        try:
            with store.transaction():
                note = learner_store.insert(store, "learner_notes", s.learner_id, session_id=s.session_id,
                                            text=text, created_at=now_iso())
                for aid in cited:
                    store.insert("learner_note_citations", note_id=note, activity_id=aid)
            written += 1
        except learner_store.LearnerUnavailable:
            log.info("note of a learner being forgotten not written")
            break
    summ["notes"] = written


prompts.TASKS.setdefault(
    "notes", "After the session, write at most five short notes (each at most 200 characters) about how this "
             "learner reads and learns, from the activities in <activities> and the context in <learner_context>. "
             "Each note cites the activity ids it rests on. Describe patterns, not single slips; never personal "
             "details.")
