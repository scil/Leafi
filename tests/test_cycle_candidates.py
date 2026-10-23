"""ADR-0013 → Cycles and candidates, ADR-0017 §8.1, §8.5: closing a cycle settles what it still owns; recovery.
Never mocked (docs/engineering/testing.md)."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store, dumps, loads
from leafi.study import miscues
from leafi.study.alignment import ReadingState
from leafi.study.harness import rows
from tests import seed

TEXT = "The fox ran home. It was late and dark."


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _cycle_with(store, words):
    book, page, rev = seed.book_page(store, TEXT)
    s = seed.session(store, book)
    read = seed.page_read(store, s, page, rev)
    aid = rows.start_activity(store, session_id=s, kind="read_listen", cycle_id=None)
    cyc = rows.open_cycle(store, s, aid)
    st = ReadingState.from_text(TEXT, page_read_id=read, revision_id=rev)
    ids = {}
    for w in words:
        mid = seed.miscue(store, read, rev, TEXT, w)
        store.execute("UPDATE miscues SET cycle_id=? WHERE id=?", (cyc, mid))
        i = next(i for i, t in enumerate(st.tokens) if t.text == w)
        st.tokens[i].status, st.tokens[i].miscue_id = "candidate", mid
        ids[w] = mid
    store.execute("UPDATE page_reads SET reading_state=? WHERE id=?", (dumps(st.to_json()), read))
    return s, cyc, read, ids


@pytest.mark.parametrize("reason,expect", [("wrap", "not_practised"), ("next_reading", "not_practised"),
                                           ("stop", "skipped"), ("interrupted", "interrupted")])
def test_unpractised_candidates_settle_by_the_close_reason(store, reason, expect):
    _, cyc, read, ids = _cycle_with(store, ["fox", "dark"])
    assert sorted(rows.close_cycle(store, cyc, reason)) == sorted(ids.values())
    for mid in ids.values():
        assert seed.status_of(store, mid) == ("unsure", expect)
    c = store.one("SELECT status, closed_reason, closed_at FROM cycles WHERE id=?", (cyc,))
    assert (c["status"], c["closed_reason"]) == ("closed", reason) and c["closed_at"]


def test_a_practised_candidate_gets_practices_final_status_not_not_practised(store):
    """ADR-0013 rev 3: a recorded `fail` is not lost to `not_practised` at the cycle's close."""
    _, cyc, read, ids = _cycle_with(store, ["fox", "home", "dark", "late"])
    miscues.record_practice(store, ids["fox"], 1, "disagreed")  # a page turn cut practice after one fail
    miscues.record_practice(store, ids["home"], 1, "idle")
    miscues.record_practice(store, ids["dark"], 1, "unclear")
    miscues.record_practice(store, ids["late"], 1, "disagreed")
    miscues.record_practice(store, ids["late"], 2, "matched")
    rows.close_cycle(store, cyc, "wrap")
    assert seed.status_of(store, ids["fox"]) == ("unsure", "disagreed")
    assert seed.status_of(store, ids["home"]) == ("unsure", "idle")
    assert seed.status_of(store, ids["dark"]) == ("unsure", "unclear")
    assert seed.status_of(store, ids["late"]) == ("withdrawn", "practice")


def test_the_token_is_settled_by_miscue_id_in_its_page_read(store):
    _, cyc, read, ids = _cycle_with(store, ["fox"])
    rows.close_cycle(store, cyc, "wrap")
    st = ReadingState.from_json(TEXT, loads(store.one("SELECT reading_state FROM page_reads WHERE id=?",
                                                      (read,))["reading_state"]))
    assert [t.status for t in st.tokens if t.miscue_id == ids["fox"]] == ["settled"]


def test_a_settled_candidate_is_not_touched_again(store):
    _, cyc, read, ids = _cycle_with(store, ["fox", "dark"])
    miscues.set_status(store, ids["fox"], "withdrawn", reason="self_corrected")
    rows.close_cycle(store, cyc, "stop")
    assert seed.status_of(store, ids["fox"]) == ("withdrawn", "self_corrected")
    assert seed.status_of(store, ids["dark"]) == ("unsure", "skipped")


def test_practice_final_status_rules():
    assert rows.practice_final(["disagreed", "matched"]) == ("withdrawn", "practice")
    assert rows.practice_final(["skipped"]) == ("unsure", "skipped")
    assert rows.practice_final(["disagreed", "idle"]) == ("unsure", "disagreed")
    assert rows.practice_final(["unclear", "idle"]) == ("unsure", "idle")
    assert rows.practice_final(["idle", "unclear"]) == ("unsure", "unclear")


def test_recovery_interrupts_the_running_activity_and_closes_the_open_cycle(store):
    s, cyc, read, ids = _cycle_with(store, ["fox"])
    running = rows.start_activity(store, session_id=s, kind="practise_errors", cycle_id=cyc)
    assert rows.recover(store) == [s]
    assert store.one("SELECT status FROM activities WHERE id=?", (running,))["status"] == "interrupted"
    assert store.one("SELECT status, closed_reason FROM cycles WHERE id=?", (cyc,))["closed_reason"] == "interrupted"
    assert seed.status_of(store, ids["fox"]) == ("unsure", "interrupted")
    sess = store.one("SELECT ended_at, summary FROM reading_sessions WHERE id=?", (s,))
    assert sess["ended_at"] and loads(sess["summary"])["interrupted"] is True
    assert rows.recover(store) == []  # idempotent
