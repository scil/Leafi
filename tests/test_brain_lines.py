"""The Brain's own lines in negotiate (M7 design D13, D2): `say_before` is the announcement only at `bands.announce`
and only for the activity the Brain proposed; its rationale only for that activity; both carry the call's output
provenance, never `system`."""

from __future__ import annotations

from leafi.core.provenance import SYSTEM, Provenance
from leafi.study.brain.sequence import Proposal
from leafi.study.harness.menu import allowed
from leafi.study.harness.negotiate import negotiate
from leafi.study.harness.policy import default_selection
from leafi.study.harness.state import Facts, Spec
from tests.harness_helpers import make_session

READING = Facts(has_book=True, unread_current=True)
FROM_ADA = Provenance("derived_from_learner", (1,))


def _prop(s, kind: str) -> Proposal:
    return Proposal(Spec(kind, default_selection(kind, s.facts()), source="brain"),
                    rationale="You read this page well yesterday.", say_before="On we go with the fox!",
                    provenance=FROM_ADA)


async def test_at_announce_the_brains_say_before_announces_its_activity(tmp_path):
    s = make_session(tmp_path, facts=READING, values={"autonomy": 9})
    out = await negotiate(s, _prop(s, "read_listen"), allowed(s), s.epoch())
    assert out.activity.kind == "read_listen"
    assert s.talk.said == ["On we go with the fox!"] and s.talk.provenances == [FROM_ADA]


async def test_say_before_is_not_spoken_for_another_activity_or_below_announce(tmp_path):
    s = make_session(tmp_path, facts=READING, values={"autonomy": 9})
    s.boundary.excluded.add("read_listen")  # the Brain's activity was refused: the next candidate is announced
    await negotiate(s, _prop(s, "read_listen"), allowed(s), s.epoch())
    assert "On we go with the fox!" not in s.talk.said and s.talk.provenances[0] == SYSTEM

    s = make_session(tmp_path / "argue", facts=READING, values={"autonomy": 5}, replies=["yes"])
    await negotiate(s, _prop(s, "read_listen"), allowed(s), s.epoch())
    assert s.talk.said == ["You read this page well yesterday."] and s.talk.provenances == [FROM_ADA]
