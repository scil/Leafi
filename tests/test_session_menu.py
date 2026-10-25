"""ADR-0017 §3.2: `allowed(s)`; always contains `end`."""

from __future__ import annotations

from leafi.study.harness import rows
from leafi.study.harness.menu import allowed
from leafi.study.harness.state import Facts
from tests.harness_helpers import make_session, past_soft_deadline

READING = Facts(has_book=True, unread_current=True)


def test_the_base_menu_is_end_and_break(tmp_path):
    assert allowed(make_session(tmp_path)) == {"end", "break"}


def test_after_the_soft_deadline_only_end(tmp_path):
    s = past_soft_deadline(make_session(tmp_path, facts=READING))
    assert allowed(s) == {"end"}


def test_reading_review_and_recall_need_their_facts(tmp_path):
    s = make_session(tmp_path, facts=Facts(has_book=True, unread_current=True, anki_reachable=True, anki_due=3,
                                           recall_due=(1,)))
    assert allowed(s) == {"end", "break", "read_listen", "read_aloud", "review_anki", "recall_items"}
    s2 = make_session(tmp_path / "b", facts=Facts(anki_reachable=True, anki_due=3, reviews_goal_met=True))
    assert "review_anki" not in allowed(s2)


def test_cycle_kinds_need_an_open_cycle_and_ledger_room(tmp_path):
    f = Facts(has_book=True, unread_current=True, open_candidates=(1, 2), cardable_items=(7,), read_sentences=True,
              new_item_candidates=(9,))
    assert "practise_errors" not in allowed(make_session(tmp_path / "a", facts=f))  # no cycle yet
    s = make_session(tmp_path / "b", facts=f, cycle=True)
    m = allowed(s)
    assert {"practise_errors", "add_cards"} <= m
    assert not m & {"teach_items", "quiz", "learner_questions"}  # no Brain: nothing Brain-only (M7)
    s0 = make_session(tmp_path / "c", facts=f, cycle=True, values={"practice.max_errors": 0, "cards.max": 0})
    assert not allowed(s0) & {"practise_errors", "add_cards"}


def test_the_cycle_cap_leaves_only_reading_and_end(tmp_path):
    f = Facts(has_book=True, unread_current=True, open_candidates=(1,), cardable_items=(7,))
    s = make_session(tmp_path, facts=f, cycle=True, values={"limits.activities_per_cycle": 2})
    rows.start_activity(s.store, session_id=s.session_id, kind="read_listen", cycle_id=s.cycle_id, continuation=True)
    assert "practise_errors" in allowed(s)  # one boundary activity + a continuation: below the cap
    rows.start_activity(s.store, session_id=s.session_id, kind="practise_errors", cycle_id=s.cycle_id)
    assert allowed(s) == {"read_listen", "read_aloud", "end"}
