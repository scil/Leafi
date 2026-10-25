"""Learners and the learner-scoped writes (ADR-0018 §1, §3, §7.1). A core module: `leafi.study` and, later,
`leafi.privacy` import it; it imports nothing from either.

The fence of ADR-0018 §1, by the **owning learner** since ADR-0021 E9 (the provenance columns are gone): every
write of a learner-owned row is a conditional statement that runs only while the row's owner exists and is not
being forgotten, so a write that races `forget --learner` is refused instead of leaving a copy behind.

- `insert` for `DIRECT_OWNED` tables (owner in `learner_id`);
- `insert_named` for `SESSION_OWNED` tables (owner = the learner of the row's `session_id`; a missing session or
  learner refuses, never a foreign-key error);
- `update_named` for an UPDATE that writes a column outside `tests/test_architecture.py`'s maintenance allow-list,
  with the owner check in the UPDATE's own `WHERE`;
- `adopt_session` for the one write that moves a session to another learner.

`tests/test_architecture.py` refuses such a write anywhere else.
"""

from __future__ import annotations

import sqlite3

from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.core.text import placeholder_reason

DIRECT_OWNED = frozenset({"reading_sessions", "knowledge_items", "difficulties", "retrieval_events", "learner_notes",
                          "book_notes", "review_answers", "anki_outbox", "consents", "encounters"})
DIRECT = DIRECT_OWNED  # the name M5–M7 code uses
# Written after `post_done_at` too (the audit flush, post-session steps), so fenced; the other session tables are
# written only by a live session or by recovery, which checks the owner itself (ADR-0021 E9).
SESSION_OWNED = frozenset({"activities", "utterances", "brain_calls"})

_LIVE = "EXISTS(SELECT 1 FROM learners WHERE id = ? AND forgetting = 0)"
_LIVE_SESSION = ("EXISTS(SELECT 1 FROM reading_sessions rs JOIN learners l ON l.id = rs.learner_id "
                 "WHERE rs.id = {sid} AND l.forgetting = 0)")


class LearnerUnavailable(RuntimeError):
    """The row's owner does not exist or is being forgotten: the write was refused."""


class LearnerChoice(LookupError):
    """No learner could be chosen without the household saying which (the message lists them)."""


def insert(store: Store, table: str, learner_id: int, **cols) -> int:
    """Insert one row owned by `learner_id`; refused (LearnerUnavailable) unless the owner exists with
    `forgetting = 0`, checked in the same statement as the insert."""
    if table not in DIRECT_OWNED:
        raise ValueError(f"{table} is not a learner-owned table")
    cols = {"learner_id": learner_id, **cols}
    names, marks = ", ".join(cols), ", ".join("?" for _ in cols)
    cur = store.execute(f"INSERT INTO {table}({names}) SELECT {marks} WHERE {_LIVE}", (*cols.values(), learner_id))
    if cur.rowcount != 1:
        raise LearnerUnavailable(f"{table}: learner #{learner_id} missing or being forgotten")
    return int(cur.lastrowid)


def insert_named(store: Store, table: str, **cols) -> int:
    """Insert a row of a session-owned table (`activities`, `utterances`, `brain_calls`): refused unless the
    learner of its `session_id` exists and is not being forgotten, checked in the same statement."""
    if table not in SESSION_OWNED:
        raise ValueError(f"{table}: use insert() for a learner-owned table, or it is not fenced")
    names, marks = ", ".join(cols), ", ".join("?" for _ in cols)
    cur = store.execute(f"INSERT INTO {table}({names}) SELECT {marks} WHERE {_LIVE_SESSION.format(sid='?')}",
                        (*cols.values(), cols.get("session_id")))
    if cur.rowcount != 1:
        raise LearnerUnavailable(f"{table}: session #{cols.get('session_id')}'s learner missing or being forgotten")
    return int(cur.lastrowid)


def update_named(store: Store, table: str, row_id: int, **cols) -> None:
    """An UPDATE of one row that writes a non-maintenance column: refused unless the row's owner exists and is not
    being forgotten, checked in the UPDATE's own `WHERE` (no separate owner read)."""
    if table in DIRECT_OWNED:
        owner = f"EXISTS(SELECT 1 FROM learners l WHERE l.id = {table}.learner_id AND l.forgetting = 0)"
    elif table in SESSION_OWNED:
        owner = _LIVE_SESSION.format(sid=f"{table}.session_id")
    else:
        raise ValueError(f"{table} is not a learner- or session-owned table")
    sets = ", ".join(f"{k}=?" for k in cols)
    cur = store.execute(f"UPDATE {table} SET {sets} WHERE id = ? AND {owner}", (*cols.values(), row_id))
    if cur.rowcount != 1:
        raise LearnerUnavailable(f"{table} #{row_id}: its learner is missing or being forgotten")


def adopt_session(store: Store, session_id: int, guest: int, learner: int) -> bool:
    """Move a session (and the guest's egress attempts so far, M5 design D5) to an enrolled learner who is not being
    forgotten, then delete the guest row once it owns nothing: one transaction, the caller's (ADR-0018 §1)."""
    moved = store.execute(
        "UPDATE reading_sessions SET learner_id=? WHERE id=? AND EXISTS(SELECT 1 FROM learners WHERE id=? "
        "AND kind='learner' AND forgetting=0)", (learner, session_id, learner)).rowcount
    if not moved:
        return False
    if guest != learner:
        store.execute("UPDATE egress_log SET learner_id=? WHERE learner_id=?", (learner, guest))
        store.execute("DELETE FROM learners WHERE id=? AND kind='guest' AND NOT EXISTS(SELECT 1 FROM "
                      "reading_sessions WHERE learner_id=?)", (guest, guest))
    return True


# ---------------------------------------------------------------- learners


def create(store: Store, display_name: str, *, kind: str = "learner", birth_year: int | None = None,
           school_year: int | None = None, settings: dict | None = None) -> int:
    name = display_name.strip()
    if not name:
        raise ValueError("a learner needs a name")
    why = placeholder_reason(name)
    if why is not None:
        raise ValueError(f"{name!r} is not a learner's name: {why}; type the child's own first name")
    return store.insert("learners", kind=kind, display_name=name, birth_year=birth_year, school_year=school_year,
                        settings=dumps(settings or {}), created_at=now_iso())


def get(store: Store, learner_id: int) -> sqlite3.Row | None:
    return store.one("SELECT * FROM learners WHERE id=?", (learner_id,))


def enrolled(store: Store) -> list[sqlite3.Row]:
    """Learners (not guests, not `anonymous`) that are not being forgotten, oldest first."""
    return store.all("SELECT * FROM learners WHERE kind='learner' AND forgetting=0 ORDER BY id")


def setting(store: Store, learner_id: int, key: str, default=None):
    row = get(store, learner_id)
    return loads(row["settings"], {}).get(key, default) if row else default


def choose(store: Store, name: str | None, *, enrol: bool = True) -> tuple[int, bool]:
    """The learner a v1 session runs as until identification arrives (plan M3 decision): `name` matches an
    enrolled learner case-insensitively, else is enrolled when `enrol`; no name picks the only enrolled learner.
    Returns (id, newly enrolled)."""
    rows = enrolled(store)
    if name is not None:
        hits = [r for r in rows if r["display_name"].casefold() == name.strip().casefold()]
        if len(hits) == 1:
            return hits[0]["id"], False
        if hits:
            raise LearnerChoice(f"{len(hits)} learners are called {name!r}; ids {[r['id'] for r in hits]}")
        if not enrol:
            raise LearnerChoice(f"no learner called {name!r}; enrolled: {_names(rows)}")
        return create(store, name), True
    if len(rows) == 1:
        return rows[0]["id"], False
    if not rows:
        raise LearnerChoice("no learner yet: start with --learner followed by the child's first name in quotes")
    raise LearnerChoice(f"say who is reading with --learner; enrolled: {_names(rows)}")


def ensure_learner(store: Store) -> int:
    """For tests and callers that build a session by hand: the only learner, enrolling "Learner" in an empty
    database. The CLI never uses it; it calls `choose`."""
    rows = enrolled(store)
    if len(rows) == 1:
        return rows[0]["id"]
    if not rows:
        return create(store, "Learner")
    raise LearnerChoice(f"several learners; pass one: {_names(rows)}")


def _names(rows: list[sqlite3.Row]) -> str:
    return ", ".join(f"{r['display_name']} (#{r['id']})" for r in rows) or "none"


def session_learner(store: Store, session_id: int) -> int | None:
    row = store.one("SELECT learner_id FROM reading_sessions WHERE id=?", (session_id,))
    return row["learner_id"] if row else None


def read_learner(store: Store, page_read_id: int) -> int | None:
    row = store.one("SELECT s.learner_id FROM page_reads pr JOIN reading_sessions s ON s.id = pr.session_id "
                    "WHERE pr.id=?", (page_read_id,))
    return row["learner_id"] if row else None
