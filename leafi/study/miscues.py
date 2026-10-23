"""Miscue rows: the judgement layer over observations (data-model.md). Status moves only forward along
ADR-0013 (Practice, Interrupted session, Correction interaction); rows are never deleted except by the
parent's `forget` commands.
"""

from __future__ import annotations

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, now_iso
from leafi.study import knowledge

FORWARD = {
    "candidate": {"confirmed", "unsure", "withdrawn", "invalidated"},
    "unsure": {"invalidated"},
    "confirmed": {"invalidated"},
    "withdrawn": set(),
    "invalidated": set(),
}
OPEN = ("candidate",)


class IllegalTransition(ValueError):
    pass


def create(store: Store, *, observation_id: int | None, page_read_id: int, revision_id: int, expected: str,
           token_index: int, char_span: tuple[int, int], heard: str | None, cycle_id: int | None = None,
           origin: str | None = None) -> int:
    """A candidate, owned by `cycle_id` when a harness `read_listen` created it (ADR-0017 §8.1)."""
    return store.insert("miscues", observation_id=observation_id, page_read_id=page_read_id,
                        page_revision_id=revision_id, cycle_id=cycle_id, expected=expected,
                        expected_token_index=token_index, expected_char_span=dumps(list(char_span)), heard=heard,
                        origin=origin or ("deletion" if heard is None else "substitution"), status="candidate",
                        evidence="none", updated_at=now_iso())


def set_status(store: Store, miscue_id: int, status: str, *, reason: str | None = None,
               evidence: str | None = None, score: float | None = None) -> None:
    row = store.one("SELECT status, page_read_id FROM miscues WHERE id=?", (miscue_id,))
    if row is None:
        raise LookupError(f"miscue {miscue_id}")
    if status not in FORWARD[row["status"]]:
        raise IllegalTransition(f"miscue {miscue_id}: {row['status']} -> {status}")
    cols = {"status": status, "updated_at": now_iso()}
    if status == "withdrawn":
        cols["withdrawn_reason"] = reason
    elif status == "unsure":
        cols["unsure_reason"] = reason
    elif status == "invalidated":
        cols["invalidated_reason"] = reason
    if evidence is not None:
        cols["evidence"] = evidence
    if score is not None:
        cols["score"] = score
    sets = ", ".join(f"{k}=?" for k in cols)
    with store.transaction():  # evidence and the Difficulties that depend on it change together (review 1 #17)
        store.execute(f"UPDATE miscues SET {sets} WHERE id=?", (*cols.values(), miscue_id))
        if status in ("confirmed", "unsure", "invalidated"):
            knowledge.recompute_difficulties(store, learner_store.read_learner(store, row["page_read_id"]))


def open_for_read(store: Store, page_read_id: int) -> list[int]:
    return [r["id"] for r in store.all("SELECT id FROM miscues WHERE page_read_id=? AND status='candidate' "
                                       "ORDER BY expected_token_index", (page_read_id,))]


def record_practice(store: Store, miscue_id: int, attempt: int, outcome: str, evidence: str = "none") -> int:
    return store.insert("practices", miscue_id=miscue_id, attempt=attempt, outcome=outcome, evidence=evidence,
                        created_at=now_iso())


def settle_open(store: Store, page_read_id: int, reason: str) -> list[int]:
    """Page settlement / interrupted close: every open candidate of the page read → unsure(reason)."""
    ids = open_for_read(store, page_read_id)
    for mid in ids:
        set_status(store, mid, "unsure", reason=reason)
    return ids
