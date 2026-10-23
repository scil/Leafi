"""What the harness records itself (ADR-0017 §7.2): activity rows, cycles, and their closing; startup recovery
(§8.5). Cycle closing follows ADR-0013 → Cycles and candidates; tokens are always found by `miscue_id`."""

from __future__ import annotations

import logging

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.study import miscues, records
from leafi.study.alignment import ReadingState
from leafi.study.harness.status import ActivityStatus, check

log = logging.getLogger("leafi.harness")

# ADR-0013 Practice step 4: practices.outcome → the attempt's result
_ATTEMPT = {"matched": "pass", "disagreed": "fail", "skipped": "skip", "idle": "idle", "unclear": "unclear"}
CLOSE_REASONS = ("next_reading", "wrap", "stop", "interrupted", "not_practised")


def start_activity(store: Store, *, session_id: int, kind: str, cycle_id: int | None, params: dict | None = None,
                   continuation: bool = False, arm: str | None = None, propensity: float | None = None,
                   policy_version: str | None = None, decided_by: str | None = None, override: str | None = None,
                   autonomy: int | None = None, epoch: int = 0) -> int:
    check(kind, ActivityStatus.COMPLETED)  # a known kind
    none = learner_store.prov("system")
    return store.insert(
        "activities", session_id=session_id, cycle_id=cycle_id, kind=kind, continuation=int(continuation),
        params=dumps(params or {}), arm=arm, propensity=propensity, policy_version=policy_version,
        decided_by=decided_by, override=override, autonomy=autonomy, epoch=epoch, status=ActivityStatus.RUNNING,
        started_at=now_iso(), outcome_provenance_class=none[0], outcome_source_learners=none[1],
        assessment_provenance_class=none[0], assessment_source_learners=none[1])


def finish_activity(store: Store, activity_id: int, status: str, outcome: dict | None = None,
                    learner_id: int | None = None) -> ActivityStatus:
    """Close a running row with a status its kind may end in. An outcome that reports what the learner did is
    `derived_from_learner`."""
    row = store.one("SELECT kind, status FROM activities WHERE id=?", (activity_id,))
    st = check(row["kind"], status)
    if row["status"] != ActivityStatus.RUNNING:
        raise ValueError(f"activity {activity_id} already ended {row['status']}")
    pc, src = learner_store.prov("derived_from_learner", [learner_id]) if outcome and learner_id else \
        learner_store.prov("system")
    store.execute("UPDATE activities SET status=?, ended_at=?, outcome=?, outcome_provenance_class=?, "
                  "outcome_source_learners=? WHERE id=?",
                  (st, now_iso(), dumps(outcome) if outcome is not None else None, pc, src, activity_id))
    return st


def open_cycle(store: Store, session_id: int, opened_by_activity: int | None) -> int:
    return store.insert("cycles", session_id=session_id, status="open", opened_by_activity=opened_by_activity,
                        opened_at=now_iso())


def open_cycle_of(store: Store, session_id: int) -> int | None:
    row = store.one("SELECT id FROM cycles WHERE session_id=? AND status='open' ORDER BY id DESC LIMIT 1",
                    (session_id,))
    return row["id"] if row else None


def open_candidates(store: Store, cycle_id: int) -> list[int]:
    return [r["id"] for r in store.all("SELECT id FROM miscues WHERE cycle_id=? AND status='candidate' ORDER BY id",
                                       (cycle_id,))]


def practice_final(outcomes: list[str]) -> tuple[str, str]:
    """ADR-0013 Practice step 4 over every `practices` row of a miscue, in attempt order."""
    results = [_ATTEMPT[o] for o in outcomes]
    if "pass" in results:
        return "withdrawn", "practice"
    if "skip" in results:
        return "unsure", "skipped"
    if "fail" in results:
        return "unsure", "disagreed"
    if results and results[-1] == "idle":
        return "unsure", "idle"
    return "unsure", "unclear"


def _settle_token(store: Store, miscue_id: int) -> None:
    row = store.one("SELECT pr.id, pr.reading_state, rev.text FROM miscues m JOIN page_reads pr ON pr.id = "
                    "m.page_read_id JOIN page_revisions rev ON rev.id = pr.page_revision_id WHERE m.id=?",
                    (miscue_id,))
    if row is None or not row["reading_state"]:
        return
    st = ReadingState.from_json(row["text"], loads(row["reading_state"]))
    for t in st.tokens:
        if t.miscue_id == miscue_id and t.status == "candidate":
            t.status = "settled"
    store.execute("UPDATE page_reads SET reading_state=? WHERE id=?", (dumps(st.to_json()), row["id"]))


def close_cycle(store: Store, cycle_id: int, reason: str) -> list[int]:
    """One transaction: every open candidate gets its final status, its token is settled, the cycle closes."""
    if reason not in CLOSE_REASONS:
        raise ValueError(f"cycle close reason {reason!r}")
    settled = []
    with store.transaction():
        for mid in open_candidates(store, cycle_id):
            outcomes = [r["outcome"] for r in store.all(
                "SELECT outcome FROM practices WHERE miscue_id=? ORDER BY attempt", (mid,))]
            if outcomes:
                status, why = practice_final(outcomes)
            else:
                status, why = "unsure", {"stop": "skipped", "interrupted": "interrupted"}.get(reason,
                                                                                             "not_practised")
            miscues.set_status(store, mid, status, reason=why)
            _settle_token(store, mid)
            settled.append(mid)
        store.execute("UPDATE cycles SET status='closed', closed_reason=?, closed_at=? WHERE id=?",
                      (reason, now_iso(), cycle_id))
    return settled


def recover(store: Store) -> list[int]:
    """Startup recovery (ADR-0017 §8.5), run with the speech lease held: a stale session's `running` activity
    becomes `interrupted`, its open cycle closes with reason `interrupted`; then the v1 path settles page reads
    and ends the session with `summary.interrupted`."""
    stale = [r["id"] for r in store.all("SELECT id FROM reading_sessions WHERE ended_at IS NULL")]
    for sid in stale:
        with store.transaction():
            store.execute("UPDATE activities SET status=?, ended_at=? WHERE session_id=? AND status=?",
                          (ActivityStatus.INTERRUPTED, now_iso(), sid, ActivityStatus.RUNNING))
            for c in store.all("SELECT id FROM cycles WHERE session_id=? AND status='open'", (sid,)):
                close_cycle(store, c["id"], "interrupted")
    records.close_stale_sessions(store)  # also recomputes each learner's Difficulties
    return stale
