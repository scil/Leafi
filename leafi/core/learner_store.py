"""Learners and the learner-scoped writes (ADR-0018 §1, §3, §7.1). A core module: `leafi.study` and, later,
`leafi.privacy` import it; it imports nothing from either.

Every row of a direct-owner table is inserted through `insert`, which is a conditional insert: it writes only while
the owner and every source learner of its text exist and are not being forgotten, so a write that races
`forget --learner` is refused instead of leaving a copy behind (the fence of ADR-0018 §1).

M7 design D22 extends the fence to every write that names a learner: `insert_named` for tables with provenance
columns but no owner column, `update_named` for an UPDATE that sets provenance columns, and `adopt_session` for the
one write that moves a session to another learner. `tests/test_architecture.py` refuses such a write anywhere else.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from leafi.core.provenance import PARENT_SOURCE
from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.core.text import placeholder_reason

DIRECT = frozenset({"reading_sessions", "knowledge_items", "difficulties", "retrieval_events", "learner_notes",
                    "book_notes", "review_answers", "anki_outbox", "consents", "encounters"})
CLASSES = ("page", "system", "learner", "derived_from_learner", "parent")
# (table, provenance-class column, source-learners column) for every stored text that can reach a payload (§3).
PROVENANCE = (
    ("utterances", "provenance_class", "source_learners"),
    ("activities", "outcome_provenance_class", "outcome_source_learners"),
    ("activities", "assessment_provenance_class", "assessment_source_learners"),
    ("brain_calls", "payload_provenance_class", "payload_source_learners"),
    ("brain_calls", "response_provenance_class", "response_source_learners"),
    ("learner_notes", "provenance_class", "source_learners"),
    ("book_notes", "provenance_class", "source_learners"),
    ("encounters", "context_provenance_class", "context_source_learners"),
    ("encounters", "explanation_provenance_class", "explanation_source_learners"),
    ("anki_outbox", "card_provenance_class", "card_source_learners"),
)


class LearnerUnavailable(RuntimeError):
    """The owner or a source learner does not exist or is being forgotten: the write was refused."""


class LearnerChoice(LookupError):
    """No learner could be chosen without the household saying which (the message lists them)."""


def prov(cls: str, sources: Iterable[int] = ()) -> tuple[str, str]:
    """A provenance pair (class, json source ids) for a writer's columns."""
    if cls not in CLASSES:
        raise ValueError(f"provenance class {cls!r}")
    return cls, dumps(sorted(set(sources)))


def stated_sources(cols: dict) -> set[int]:
    """The learner ids a row's own `*source_learners` columns name: what the fence must check (codex M3 #3).
    `PARENT_SOURCE` names no learner and is left out (M7 design D2)."""
    out: set[int] = set()
    for name, value in cols.items():
        if name.endswith("source_learners"):
            out.update(int(i) for i in loads(value, []))
    out.discard(PARENT_SOURCE)
    return out


def insert(store: Store, table: str, learner_id: int, *, sources: Iterable[int] = (), **cols) -> int:
    """Insert one row owned by `learner_id`; refused (LearnerUnavailable) unless the owner and every source learner
    (`sources` and every id the row's provenance columns name) exist with `forgetting = 0`, checked in the same
    statement as the insert."""
    if table not in DIRECT:
        raise ValueError(f"{table} is not a learner-owned table")
    cols = {"learner_id": learner_id, **cols}
    ids = sorted({learner_id, *sources, *stated_sources(cols)} - {PARENT_SOURCE})
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    idm = ", ".join("?" for _ in ids)
    cur = store.execute(
        f"INSERT INTO {table}({names}) SELECT {marks} WHERE "
        f"(SELECT COUNT(*) FROM learners WHERE id IN ({idm}) AND forgetting = 0) = ?",
        (*cols.values(), *ids, len(ids)))
    if cur.rowcount != 1:
        raise LearnerUnavailable(f"{table}: learner(s) {ids} missing or being forgotten")
    return int(cur.lastrowid)


def _fence(ids: list[int]) -> tuple[str, tuple]:
    marks = ", ".join("?" for _ in ids)
    return f"(SELECT COUNT(*) FROM learners WHERE id IN ({marks}) AND forgetting = 0) = ?", (*ids, len(ids))


PROVENANCE_TABLES = frozenset(t for t, _, _ in PROVENANCE)
# The learner a row belongs to, for a provenance table without its own `learner_id` (its session's learner).
_OWNER_SQL = {
    "activities": "SELECT rs.learner_id FROM activities a JOIN reading_sessions rs ON rs.id = a.session_id "
                  "WHERE a.id = ?",
    "utterances": "SELECT rs.learner_id FROM utterances u JOIN reading_sessions rs ON rs.id = u.session_id "
                  "WHERE u.id = ?",
}


def insert_named(store: Store, table: str, *, sources: Iterable[int] = (), **cols) -> int:
    """Insert a row of a provenance table that has no owner column (`utterances`, `activities`, `brain_calls`):
    refused unless every learner its provenance columns (and `sources`) name exists and is not being forgotten,
    checked in the same statement (M7 design D22)."""
    if table not in PROVENANCE_TABLES or table in DIRECT:
        raise ValueError(f"{table}: use insert() for a learner-owned table, or it has no provenance")
    ids = sorted({*sources, *stated_sources(cols)} - {PARENT_SOURCE})
    names, marks = ", ".join(cols), ", ".join("?" for _ in cols)
    fence, args = _fence(ids)
    cur = store.execute(f"INSERT INTO {table}({names}) SELECT {marks} WHERE {fence}", (*cols.values(), *args))
    if cur.rowcount != 1:
        raise LearnerUnavailable(f"{table}: learner(s) {ids} missing or being forgotten")
    return int(cur.lastrowid)


def row_owner(store: Store, table: str, row_id: int) -> int | None:
    sql = _OWNER_SQL.get(table) or (f"SELECT learner_id FROM {table} WHERE id = ?" if table in DIRECT else None)
    if sql is None:
        return None
    row = store.one(sql, (row_id,))
    return row[0] if row else None


def update_named(store: Store, table: str, row_id: int, **cols) -> None:
    """An UPDATE of one row that sets provenance columns: refused unless the row's own learner and every learner
    the new columns name exist and are not being forgotten, in the same statement (M7 design D22)."""
    if table not in PROVENANCE_TABLES:
        raise ValueError(f"{table} has no provenance columns")
    owner = row_owner(store, table, row_id)
    ids = sorted((({owner} if owner else set()) | stated_sources(cols)) - {PARENT_SOURCE})
    sets = ", ".join(f"{k}=?" for k in cols)
    fence, args = _fence(ids)
    cur = store.execute(f"UPDATE {table} SET {sets} WHERE id = ? AND {fence}", (*cols.values(), row_id, *args))
    if cur.rowcount != 1:
        raise LearnerUnavailable(f"{table} #{row_id}: learner(s) {ids} missing or being forgotten")


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
