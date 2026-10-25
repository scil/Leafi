"""Item status as a fold over evidence (ADR-0017 §6.2; M7 design D17): the pure fold rule by rule, the design's
hand-run, mastery in both modes, the recall spacing, and `apply` / `forget --session` on a real database."""

from __future__ import annotations

import pytest

from leafi.core import learner_store
from leafi.core.storage import Store, now_iso
from leafi.study import item_status, knowledge, records
from leafi.study.item_status import Event, Mastery, Retrieval, fold
from tests import seed

R = Mastery(known_days=21)  # retrievals mode, 6 successes over 3 days
A = Mastery(mode="anki", known_days=21)


def ret(n: int, day: str, outcome: str = "success") -> Retrieval:
    return Retrieval(f"{day}T10:00:{n:02d}", n, day, outcome)


def ev(n: int, event: str, card: int | None = None, ivl: float | None = None, lapses: int | None = None) -> Event:
    return Event(f"2026-10-0{1 + n // 10}T12:00:{n % 60:02d}", n, event, card, ivl, lapses)


# ---- the fold, rule by rule


def test_no_evidence_is_new_in_both_modes():
    assert fold([], [], R) == ("new", None)
    assert fold([], [], A) == ("new", None)


def test_ignore_wins_and_unignore_only_removes_that_rule():
    assert fold([ret(1, "2026-10-01")], [ev(2, "ignore")], R) == ("ignored", None)
    assert fold([ret(1, "2026-10-01")], [ev(2, "ignore"), ev(3, "unignore")], R)[0] == "learning"
    assert fold([], [ev(2, "ignore"), ev(3, "unignore")], R) == ("new", None)  # never practised


def test_a_live_card_decides_in_both_modes():
    acked = [ev(1, "card_ack", 7)]
    assert fold([], acked, R) == ("learning", None)  # the card exists, its state is unknown
    assert fold([], acked + [ev(2, "card_state", 7, 25.0, 0)], A) == ("known", None)
    assert fold([ret(1, "2026-10-01", "fail")], acked + [ev(2, "card_state", 7, 25.0, 0)], R) == ("known", None)


def test_lapsed_only_when_the_same_card_was_known_and_its_lapses_grew():
    known_then_down = [ev(1, "card_state", 7, 25.0, 0), ev(2, "card_state", 7, 0.0, 1)]
    assert fold([], known_then_down, R)[0] == "lapsed"
    shorter_no_lapse = [ev(1, "card_state", 7, 25.0, 0), ev(2, "card_state", 7, 10.0, 0)]
    assert fold([], shorter_no_lapse, R)[0] == "learning"
    # lapses are never compared across card ids (round 4 #7): card 8 is the live one and was never known
    two_cards = [ev(1, "card_state", 7, 25.0, 0), ev(2, "card_gone", 7), ev(3, "card_state", 8, 1.0, 3)]
    assert fold([], two_cards, R)[0] == "learning"


def test_every_card_gone_leaves_the_retrievals_to_decide():
    gone = [ev(1, "card_ack", 7), ev(2, "card_state", 7, 30.0, 0), ev(3, "card_gone", 7)]
    assert fold([], gone, R) == ("new", None)
    assert fold([ret(1, "2026-10-01")], gone, R)[0] == "learning"
    back = gone + [ev(4, "card_state", 7, 30.0, 0)]  # a card restored in Anki
    assert fold([], back, R)[0] == "known"


def _successes(days: list[str]) -> list[Retrieval]:
    return [ret(i + 1, d) for i, d in enumerate(days)]


def test_retrievals_mode_known_after_six_successes_over_three_days():
    five = _successes(["2026-10-01"] * 3 + ["2026-10-02", "2026-10-03"])
    assert fold(five, [], R)[0] == "learning"
    assert fold(_successes(["2026-10-01"] * 6), [], R)[0] == "learning"  # one day only
    six = five + [ret(6, "2026-10-03")]
    assert fold(six, [], R) == ("known", None)
    assert fold(six, [], A)[0] == "learning"  # anki mode: the card is the path to known


def test_a_fail_while_known_lapses_and_the_count_restarts_from_the_lapse():
    six = _successes(["2026-10-01", "2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03", "2026-10-03"])
    lapsed = six + [ret(7, "2026-10-04", "fail")]
    assert fold(lapsed, [], R)[0] == "lapsed"
    again = lapsed + [ret(8 + i, d) for i, d in enumerate(["2026-10-05"] * 2 + ["2026-10-06"] * 2 +
                                                            ["2026-10-07"] * 2)]
    assert fold(again, [], R) == ("known", None)
    assert fold(again[:-1], [], R)[0] == "lapsed"
    # a fail while still learning resets nothing
    early_fail = [ret(1, "2026-10-01", "fail")] + six[1:] + [ret(9, "2026-10-04")]
    assert fold(early_fail, [], R)[0] == "known"


def test_the_order_of_the_inputs_does_not_matter():
    six = _successes(["2026-10-01", "2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03", "2026-10-03"])
    events = [ev(1, "ignore"), ev(2, "unignore")]
    assert fold(list(reversed(six)), list(reversed(events)), R) == fold(six, events, R)


def test_recall_spacing_one_two_four_days_and_a_fail_resets():
    assert fold([ret(1, "2026-10-01")], [], R) == ("learning", "2026-10-02")  # 1 day after the first event
    assert fold([ret(1, "2026-10-01", "fail")], [], R) == ("learning", "2026-10-02")
    two = [ret(1, "2026-10-01"), ret(2, "2026-10-02")]
    assert fold(two, [], R)[1] == "2026-10-04"  # second step: 2 days from that success
    three = two + [ret(3, "2026-10-04")]
    assert fold(three, [], R)[1] == "2026-10-08"  # third step: 4 days
    assert fold(three + [ret(4, "2026-10-08")], [], R)[1] == "2026-10-12"  # stays at 4
    assert fold(three + [ret(4, "2026-10-08", "fail")], [], R)[1] == "2026-10-09"  # back to 1 day


def test_the_designs_hand_run():
    """D17's hand-run, retrievals mode, threshold 21 days: each step's result."""
    s1 = [ret(1, "2026-10-01")]
    steps = [
        (s1, [], ("learning", "2026-10-02")),
        (s1, [ev(2, "ignore")], ("ignored", None)),
        (s1, [ev(2, "ignore"), ev(3, "unignore")], ("learning", "2026-10-02")),
        (s1, [ev(2, "ignore"), ev(3, "unignore"), ev(4, "card_ack", 7)], ("learning", None)),
        (s1, [ev(2, "ignore"), ev(3, "unignore"), ev(4, "card_ack", 7), ev(5, "card_state", 7, 25.0, 0)],
         ("known", None)),
        ([], [ev(2, "ignore"), ev(3, "unignore"), ev(4, "card_ack", 7), ev(5, "card_state", 7, 25.0, 0)],
         ("known", None)),  # forget --session S1: the card events are session-less and survive
        ([], [ev(2, "ignore"), ev(3, "unignore"), ev(4, "card_ack", 7), ev(5, "card_state", 7, 25.0, 0),
              ev(6, "card_gone", 7)], ("new", None)),
    ]
    for retrievals, events, want in steps:
        assert fold(retrievals, events, R) == want


@pytest.mark.parametrize("day", ["2026-10-01", "2026-12-31"])
def test_household_day_follows_the_zone(day):
    import datetime as dt

    noon = dt.datetime.fromisoformat(f"{day}T12:00:00+00:00")
    assert item_status.household_day("UTC", noon) == day
    late = dt.datetime.fromisoformat(f"{day}T23:30:00+00:00")
    assert item_status.household_day("Asia/Shanghai", late) > day  # already the next day there


def test_ivl_days_reads_a_negative_interval_as_seconds():
    assert item_status.ivl_days(25) == 25.0 and item_status.ivl_days(-43200) == 0.5


# ---- apply, recall due, forget --session on a database


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


def _retrieval(store, learner, item, session, day, outcome="success"):
    aid = store.insert("activities", session_id=session, kind="recall_items", status="completed",
                       started_at=now_iso())
    learner_store.insert(store, "retrieval_events", learner, item_id=item, activity_id=aid, at=f"{day}T10:00:00",
                         day=day, outcome=outcome, evidence="typed")
    item_status.apply(store, item)


def test_mastery_settings_drive_the_fold(store):
    from leafi.study.harness import settings as learner_settings

    learner = seed.learner(store)
    item = knowledge.upsert_item(store, learner, "word", "blew")
    s = seed.session(store, None, learner_id=learner)
    for day in ("2026-10-01", "2026-10-02"):
        _retrieval(store, learner, item, s, day)
    assert item_status.apply(store, item) == "learning"
    learner_settings.save(store, learner, {"mastery.min_retrievals": 2, "mastery.min_days": 2})
    assert item_status.apply(store, item) == "known"
    learner_settings.save(store, learner, {"mastery.mode": "anki"})
    assert item_status.apply(store, item) == "learning"
    with pytest.raises(learner_settings.InvalidSetting):
        learner_settings.save(store, learner, {"mastery.min_days": 15})


def test_recall_due_lists_learning_items_by_their_next_day(store):
    learner = seed.learner(store)
    a = knowledge.upsert_item(store, learner, "word", "blew")
    b = knowledge.upsert_item(store, learner, "word", "through")
    knowledge.upsert_item(store, learner, "word", "never")  # no evidence: not due
    s = seed.session(store, None, learner_id=learner)
    _retrieval(store, learner, a, s, "2026-10-01")
    _retrieval(store, learner, b, s, "2026-10-01")
    _retrieval(store, learner, b, s, "2026-10-02")
    assert item_status.recall_due(store, learner, "2026-10-01") == []
    assert item_status.recall_due(store, learner, "2026-10-02") == [a]
    assert item_status.recall_due(store, learner, "2026-10-04") == [a, b]


def test_record_refuses_a_learner_being_forgotten(store):
    learner = seed.learner(store)
    item = knowledge.upsert_item(store, learner, "word", "blew")
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (learner,))
    with pytest.raises(learner_store.LearnerUnavailable):
        item_status.record(store, learner, item, "ignore", "owner")
    assert store.one("SELECT COUNT(*) FROM item_status_events")[0] == 0


def test_forget_session_refolds_known_to_learning_and_with_nothing_left_to_new(store):
    learner = seed.learner(store)
    item = knowledge.upsert_item(store, learner, "word", "blew")
    other = knowledge.upsert_item(store, learner, "word", "through")
    s1 = seed.session(store, None, learner_id=learner)
    s2 = seed.session(store, None, learner_id=learner)
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        _retrieval(store, learner, item, s1, day)
        _retrieval(store, learner, item, s2, day)
    _retrieval(store, learner, other, s2, "2026-10-01")
    assert item_status.apply(store, item) == "known"
    item_status.record(store, learner, other, "ignore", "brain", session_id=s2)
    records.forget_session(store, s1)
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "learning"
    records.forget_session(store, s2)
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "new"
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (other,))["status"] == "new"  # ignore went


def test_forget_session_keeps_card_evidence_and_drops_its_activity_link(store):
    learner = seed.learner(store)
    item = knowledge.upsert_item(store, learner, "word", "blew")
    s = seed.session(store, None, learner_id=learner)
    aid = store.insert("activities", session_id=s, kind="review_anki", status="completed", started_at=now_iso())
    item_status.record(store, learner, item, "card_ack", "anki", card_id=7)
    item_status.record(store, learner, item, "card_state", "anki", card_id=7, ivl=30.0, lapses=0, activity_id=aid)
    store.insert("decision_records", learner_id=learner, session_id=s, at=now_iso(), turn="t1", record="{}")
    records.forget_session(store, s)
    rows = store.all("SELECT event, activity_id, session_id FROM item_status_events ORDER BY id")
    assert [(r["event"], r["activity_id"], r["session_id"]) for r in rows] == [("card_ack", None, None),
                                                                                ("card_state", None, None)]
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "known"
    assert store.one("SELECT COUNT(*) FROM decision_records")[0] == 0
    assert store.one("PRAGMA foreign_key_check") is None
