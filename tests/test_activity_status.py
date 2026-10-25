"""ADR-0017 §2, §3.1: one `ActivityStatus` enum; a kind ends only in the statuses its row lists."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store
from leafi.study.harness import rows, status
from leafi.study.harness.status import ActivityStatus as S
from tests import seed

TABLE = {  # ADR-0017 §3.1, kind-specific column; every kind also ends in EVERY_KIND
    "review_anki": {"skipped", "idle_session"},
    "read_listen": {"page_turned", "skipped", "idle_session"},
    "read_aloud": {"skipped"},
    "practise_errors": {"page_turned", "skipped"},
    "teach_items": {"skipped"},
    "recall_items": {"skipped"},
    "quiz": {"skipped", "idle_session"},
    "learner_questions": {"skipped", "idle_session"},
    "add_cards": {"skipped"},
    "break": {"skipped"},
    "end": set(),
}
EVERY = {"completed", "stopped", "lease_lost", "listener_lost_no_console", "time_up_session", "internal_error",
         "aborted_stale", "store_busy"}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def test_every_kind_ends_only_in_the_statuses_the_adr_lists():
    for kind, extra in TABLE.items():
        assert {str(s) for s in status.allowed(kind)} == EVERY | extra, kind
    assert set(status.KINDS) == set(TABLE) | {"wait"}
    for kind in TABLE:
        for st in S:
            if str(st) not in EVERY | TABLE[kind]:
                with pytest.raises(status.IllegalStatus):
                    status.check(kind, st)


def test_terminal_set_and_the_mapping_function():
    assert {str(s) for s in status.TERMINAL} == {"stopped", "lease_lost", "idle_session", "time_up_session",
                                                 "listener_lost_no_console", "internal_error"}
    assert status.for_reason("stop") == S.STOPPED
    assert status.for_reason("lease_lost") == S.LEASE_LOST
    assert status.for_reason(None) == S.INTERNAL_ERROR  # a cancellation with no latch set is a safety net


def test_an_activity_row_is_never_left_running_twice_or_ends_outside_its_table(store):
    book, page, rev = seed.book_page(store, "The fox ran.")
    s = seed.session(store, book)
    aid = rows.start_activity(store, session_id=s, kind="break", cycle_id=None, decided_by="default")
    assert store.one("SELECT status FROM activities WHERE id=?", (aid,))["status"] == "running"
    with pytest.raises(status.IllegalStatus):
        rows.finish_activity(store, aid, "page_turned")  # break cannot end page_turned
    rows.finish_activity(store, aid, "skipped")
    with pytest.raises(ValueError):
        rows.finish_activity(store, aid, "completed")
    row = store.one("SELECT status, ended_at FROM activities WHERE id=?", (aid,))
    assert row["status"] == "skipped" and row["ended_at"]


def test_an_activity_of_a_learner_being_forgotten_is_neither_started_nor_finished(store):
    """ADR-0021 E9: the fence checks the session's learner inside each statement."""
    from leafi.core import learner_store

    book, page, rev = seed.book_page(store, "The fox ran.")
    s = seed.session(store, book)
    learner = seed.learner(store)
    aid = rows.start_activity(store, session_id=s, kind="read_listen", cycle_id=None)
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (learner,))
    with pytest.raises(learner_store.LearnerUnavailable):
        rows.finish_activity(store, aid, "completed", {"sentences": 1})
    with pytest.raises(learner_store.LearnerUnavailable):
        rows.start_activity(store, session_id=s, kind="read_listen", cycle_id=None)
