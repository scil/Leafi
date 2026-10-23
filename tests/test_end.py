"""ADR-0017 §3.1: `end` is always constructible; its content owner is fixed to `code`."""

from __future__ import annotations

import pytest

from leafi.study.harness import settings as hs
from leafi.study.harness.construct import construct
from leafi.study.harness.state import Activity, Spec
from tests.harness_helpers import make_session, past_soft_deadline


def test_end_constructs_with_the_generation_budget_spent_and_after_the_soft_deadline(tmp_path):
    s = past_soft_deadline(make_session(tmp_path, values={"limits.brain_calls_per_session": 0}))
    s.ledger.brain_spent = 100
    a = construct(s, Spec("end"))
    assert isinstance(a, Activity) and a.kind == "end"


def test_ends_owner_cannot_be_set_to_brain(tmp_path):
    s = make_session(tmp_path)
    with pytest.raises(hs.InvalidSetting):
        hs.save(s.store, s.learner_id, {"policy.content.end": "brain"})
    assert s.settings["policy.content.end"] == "code"
