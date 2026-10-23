"""ADR-0017 §2.1 negotiation, the cases its Confirmation lists for `test_negotiate.py`."""

from __future__ import annotations

import pytest

from leafi.study.harness import settings as hs
from leafi.study.harness.menu import allowed
from leafi.study.harness.negotiate import DESCRIBE, REOBSERVE, Run, negotiate
from leafi.study.harness.state import Facts
from tests.harness_helpers import make_session

READING = Facts(has_book=True, unread_current=True)
KIND_OF = {v: k for k, v in DESCRIBE.items()}


def offers(s) -> list[str]:
    """The kinds Leafi offered, from its "Shall we …?" lines (autonomy 2-3)."""
    out = []
    for line in s.talk.said:
        if line.startswith("Shall we "):
            out.append(KIND_OF[line.removeprefix("Shall we ").split("?")[0]])
    return out


async def run(s):
    return await negotiate(s, None, allowed(s), s.epoch())


async def test_with_a_policy_of_only_reading_refusing_reading_never_reselects_it(tmp_path):
    order = [{"kind": "read_listen", "when": "unread"}, {"kind": "end", "when": "always"}]
    s = make_session(tmp_path, facts=READING, replies=["no", "no", "no"],
                     values={"autonomy": 2, "policy.default_order": order})
    out = await run(s)
    assert offers(s) == ["read_listen", "read_aloud", "break"]
    assert isinstance(out, Run) and out.activity.kind == "wait"


async def test_at_autonomy_2_refusing_the_default_chain_offers_other_kinds_then_waits_never_ends(tmp_path):
    s = make_session(tmp_path, facts=READING, replies=["no", "no", "no"], values={"autonomy": 2})
    out = await run(s)
    assert offers(s) == ["read_listen", "read_aloud", "break"]
    assert out.activity.kind == "wait" and out.activity.override == "wait"


async def test_a_kind_refused_earlier_and_named_later_starts_also_at_the_offer_cap(tmp_path):
    s = make_session(tmp_path, facts=READING, replies=["no", "read"],
                     values={"autonomy": 2, "negotiation.max_offers": 2})
    out = await run(s)
    assert offers(s) == ["read_listen", "read_aloud"]
    assert out.activity.kind == "read_listen"
    assert (out.activity.decided_by, out.activity.override) == ("learner", "learner_choice")


async def test_a_named_kind_that_cannot_be_built_is_said_so_and_left_out_of_the_short_list(tmp_path):
    # read_listen is on the menu (a familiar page exists) but cannot be built as named (no unread or next page)
    s = make_session(tmp_path, facts=Facts(has_book=True, familiar_pages=True), replies=["read", "no"],
                     values={"autonomy": 1})
    await run(s)
    assert "I can't read the page right now." in s.talk.said
    later = [line for line in s.talk.said if line.startswith("Would you like")][1:]
    assert later and all("read the page" not in line for line in later)
    assert "read_listen" in s.boundary.excluded


async def test_refusing_end_never_excludes_it(tmp_path):
    s = make_session(tmp_path, replies=["no", "no", "no"], values={"autonomy": 2})
    out = await run(s)
    assert offers(s) == ["break", "end", "end"]
    assert "end" not in s.boundary.excluded and out.activity.kind == "wait"


async def test_a_silence_reask_repeats_the_same_activity_and_is_not_a_new_offer(tmp_path):
    s = make_session(tmp_path, facts=READING, replies=[None, "yes"], values={"autonomy": 2})
    out = await run(s)
    assert offers(s) == ["read_listen", "read_listen"]
    assert s.boundary.offers == 1 and out.activity is s.boundary.current


async def test_with_defaults_refusing_review_and_reading_offers_read_aloud_and_break_before_end(tmp_path):
    f = Facts(has_book=True, unread_current=True, anki_reachable=True, anki_due=2)
    s = make_session(tmp_path, facts=f, replies=["no", "no", "no", "no", "no"],
                     values={"negotiation.max_offers": 5, "autonomy": 2})
    await run(s)
    assert offers(s) == ["review_anki", "read_listen", "read_aloud", "break", "end"]


async def test_exclusions_survive_reobserve(tmp_path):
    s = make_session(tmp_path, facts=READING, values={"autonomy": 2})

    class BumpingTalk(type(s.talk)):
        async def listen(self, timeout_s):
            out = await super().listen(timeout_s)
            if self.listens == 2:
                s.latch.epoch.bump()  # e.g. a page turn while Leafi waited for the answer
            return out

    s.talk = BumpingTalk(["no", "no"], s.latch)
    assert await run(s) is REOBSERVE
    assert "read_listen" in s.boundary.excluded
    s.talk.replies = ["yes"]
    out = await run(s)  # the boundary state is kept across Reobserve
    assert out.activity.kind == "read_aloud"


@pytest.mark.parametrize("reasks,asks", [(0, 1), (2, 3)])
async def test_silence_reasks_behave_as_set(tmp_path, reasks, asks):
    s = make_session(tmp_path, facts=READING, replies=[None, None, None, None],
                     values={"autonomy": 2, "negotiation.silence_reasks": reasks})
    out = await run(s)
    assert offers(s) == ["read_listen"] * asks and out.activity.kind == "wait"


@pytest.mark.parametrize("bad", [{"autonomy": 11}, {"negotiation.ask_s": 2}, {"negotiation.max_offers": 0},
                                 {"bands.ask": 5, "bands.argue": 4}, {"bands.announce": 12}, {"autonomy": "high"}])
def test_out_of_range_settings_are_refused_at_save(tmp_path, bad):
    s = make_session(tmp_path)
    with pytest.raises(hs.InvalidSetting) as e:
        hs.save(s.store, s.learner_id, bad)
    assert e.value.errors
    assert hs.load(s.store, s.learner_id).version == 1  # nothing was written


def test_a_valid_save_bumps_the_settings_version(tmp_path):
    s = make_session(tmp_path)
    after = hs.save(s.store, s.learner_id, {"autonomy": 7, "negotiation.wait_s": 45})
    assert after["autonomy"] == 7 and after.version == 2
