"""Guests (ADR-0018 §1): every session starts owned by a fresh guest row; the guest end-state table is applied
here by `finalize`, startup recovery and the sweep (the one owner)."""

from __future__ import annotations

import datetime as dt
import logging

from leafi.core.storage import Store, now_iso
from leafi.study import records

log = logging.getLogger("leafi.harness.guests")


def new_guest(store: Store) -> int:
    return store.insert("learners", kind="guest", display_name="Guest", settings="{}", created_at=now_iso())


def anonymous(store: Store) -> int:
    """The one permanent row that owns the counts of deleted guest sessions (created with the first need)."""
    row = store.one("SELECT id FROM learners WHERE kind='anonymous' ORDER BY id LIMIT 1")
    if row:
        return row["id"]
    return store.insert("learners", kind="anonymous", display_name="anonymous", settings="{}", created_at=now_iso())


def set_guest(store: Store, guest_id: int, reason: str, expires: str | None = None) -> None:
    store.execute("UPDATE learners SET guest_reason=?, guest_expires_at=? WHERE id=? AND kind='guest'",
                  (reason, expires, guest_id))


def expiry(start_iso: str, keep_days: int) -> str:
    t = dt.datetime.fromisoformat(start_iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return (t + dt.timedelta(days=keep_days)).isoformat()


def discard(store: Store, guest_id: int) -> int:
    """Delete the guest's rows; its sessions keep their counts, re-keyed to `anonymous`. Returns the sessions."""
    anon = anonymous(store)
    sessions = [r["id"] for r in store.all("SELECT id FROM reading_sessions WHERE learner_id=?", (guest_id,))]
    with store.transaction():
        for sid in sessions:
            records._delete_session_records(store, sid)
            store.execute("DELETE FROM encounters WHERE session_id=?", (sid,))
            store.execute("DELETE FROM learner_notes WHERE session_id=?", (sid,))
            store.execute("DELETE FROM book_notes WHERE session_id=?", (sid,))
            store.execute("UPDATE page_reads SET reading_state=NULL WHERE session_id=?", (sid,))
            store.execute("UPDATE reading_sessions SET learner_id=? WHERE id=?", (anon, sid))
        store.execute("DELETE FROM retrieval_events WHERE learner_id=?", (guest_id,))
        for table in ("review_answers", "difficulties", "encounters", "anki_outbox", "learner_notes", "book_notes",
                      "consents", "item_status_events", "decision_records"):
            store.execute(f"DELETE FROM {table} WHERE learner_id=?", (guest_id,))
        store.execute("DELETE FROM knowledge_items WHERE learner_id=?", (guest_id,))
        # the attempts stay on record (no body is ever stored), attributed to `anonymous` like the counts
        store.execute("UPDATE egress_log SET learner_id=? WHERE learner_id=?", (anon, guest_id))
        store.execute("DELETE FROM learners WHERE id=? AND kind='guest'", (guest_id,))
    return len(sessions)


def finalize_guest(store: Store, session_id: int, keep_days: int) -> str | None:
    """The guest end-state rows that `finalize` writes. Returns what happened, or None for a learner's session."""
    row = store.one("SELECT l.id, l.kind, l.guest_reason, s.started_at FROM reading_sessions s JOIN learners l ON "
                    "l.id = s.learner_id WHERE s.id=?", (session_id,))
    if row is None or row["kind"] != "guest":
        return None
    reason = row["guest_reason"]
    if reason is None:  # a terminal before identify returned: normalised to unconfirmed
        reason = "unconfirmed"
        set_guest(store, row["id"], reason, expiry(row["started_at"], keep_days))
    if reason == "declined" or keep_days == 0:
        discard(store, row["id"])
        return "deleted"
    return "kept"


def normalise_orphans(store: Store, keep_days: int) -> list[int]:
    """Startup recovery: every guest with neither reason nor expiry (a crash, or a finalize that could not write)."""
    done = []
    for r in store.all("SELECT l.id, MIN(s.started_at) AS started FROM learners l JOIN reading_sessions s ON "
                       "s.learner_id = l.id WHERE l.kind='guest' AND l.guest_reason IS NULL AND "
                       "l.guest_expires_at IS NULL GROUP BY l.id"):
        set_guest(store, r["id"], "unconfirmed", expiry(r["started"], keep_days))
        if keep_days == 0:
            discard(store, r["id"])
        done.append(r["id"])
    return done


def sweep(store: Store, now: str | None = None) -> list[int]:
    """Guests declined or past expiry, with a session and none still open; a conditional mark first, so two
    sweepers never act on one guest."""
    now = now or now_iso()
    gone = []
    for r in store.all("SELECT id FROM learners l WHERE kind='guest' AND forgetting=0 AND (guest_reason='declined' "
                       "OR guest_expires_at < ?) AND EXISTS(SELECT 1 FROM reading_sessions WHERE learner_id=l.id) "
                       "AND NOT EXISTS(SELECT 1 FROM reading_sessions WHERE learner_id=l.id AND post_done_at IS NULL)",
                       (now,)):
        if store.execute("UPDATE learners SET forgetting=1 WHERE id=? AND forgetting=0", (r["id"],)).rowcount:
            discard(store, r["id"])
            gone.append(r["id"])
    return gone
