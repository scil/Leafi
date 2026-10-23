"""ADR-0017 §2.1: silence below `bands.argue` never starts an activity; Leafi waits, and ends after a second wait."""

from __future__ import annotations

from leafi.study.harness import rows
from leafi.study.harness.menu import allowed
from leafi.study.harness.negotiate import negotiate
from leafi.study.harness.state import Boundary, Facts
from tests.harness_helpers import make_session

READING = Facts(has_book=True, unread_current=True)


async def test_two_silences_at_autonomy_2_start_a_30s_wait_even_at_the_cycle_cap_then_end(tmp_path):
    s = make_session(tmp_path, facts=READING, cycle=True, replies=[None, None, None, None],
                     values={"autonomy": 2, "limits.activities_per_cycle": 1})
    assert allowed(s) == {"read_listen", "read_aloud", "end"}  # at the cycle cap
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert out.activity.kind == "wait" and out.activity.params == {"seconds": 30}
    rows.start_activity(s.store, session_id=s.session_id, kind="wait", cycle_id=None)  # exempt from the menu
    s.previous_boundary_was_wait, s.boundary = True, Boundary()
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert out.activity.kind == "end"


async def test_two_unavailable_named_choices_at_autonomy_2_also_wait(tmp_path):
    s = make_session(tmp_path, facts=READING, replies=["practise", "make cards"], values={"autonomy": 2})
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert "We can't practise a few words right now." in s.talk.said
    assert "We can't make some cards right now." in s.talk.said
    assert out.activity.kind == "wait"


async def test_at_autonomy_1_leafi_offers_a_short_list(tmp_path):
    s = make_session(tmp_path, facts=READING, replies=["yes"], values={"autonomy": 1})
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert s.talk.said[0] == "Would you like to read the page, listen to me read or take a short break?"
    assert out.activity.kind == "read_listen"


async def test_from_bands_argue_silence_lets_it_start(tmp_path):
    s = make_session(tmp_path, facts=READING, replies=[None], values={"autonomy": 5})
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert out.activity.kind == "read_listen" and s.talk.listens == 1
