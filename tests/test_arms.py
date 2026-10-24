"""ADR-0017 §9 Confirmation `test_arms.py`: per-session assignment near `policy.explore_share` (10 %) over 1,000
sessions; arm, propensity, policy version and override recorded on every activity; a Brain-arm session whose
Brain gave no answer stays in the Brain arm (`brain_unavailable` counts against the Brain)."""

from __future__ import annotations

import random

from leafi.services.brain.mock import MockModel
from leafi.study.brain import call as bc
from leafi.study.harness.loop import assign_arm
from tests.harness_helpers import make_session
from tests.harness_session import env, run, summary
from tests.test_brain_session import _read

READ = [None, "The fox ran home. It was late and dark.", "/stop"]


def _brain(replies) -> bc.Brain:
    return bc.Brain({"fast": [(MockModel(replies), "mock-decide")], "standard": [], "deep": []})


def test_assignment_is_near_the_explore_share_over_1000_sessions(tmp_path):
    s = make_session(tmp_path, values={"policy.sequencer": "brain"})
    rng, arms = random.Random(2026), []
    for _ in range(1000):
        assign_arm(s, True, rng)
        arms.append((s.arm, s.propensity))
    share = sum(a == "default" for a, _ in arms) / 1000
    assert 0.08 <= share <= 0.12
    assert {p for a, p in arms if a == "default"} == {0.1} and {p for a, p in arms if a == "brain"} == {0.9}
    assign_arm(s, False, rng)  # no Brain: every session is the default policy's
    assert (s.arm, s.propensity) == ("default", 1.0)


async def test_every_activity_records_arm_propensity_policy_version_and_override(settings):
    e = env(settings, READ, learner="Ada", brain=_brain({"decide": _read}), rng=random.Random(1))
    sid = await run(e)
    rows = e.store.all("SELECT arm, propensity, policy_version, decided_by, override FROM activities "
                       "WHERE session_id=?", (sid,))
    assert rows and all(r["arm"] == "brain" and abs(r["propensity"] - 0.9) < 1e-9 and r["policy_version"]
                        for r in rows)
    assert rows[0]["decided_by"] == "brain" and rows[0]["override"] is None


async def test_a_brain_arm_fallback_stays_in_the_brain_arm(settings):
    e = env(settings, READ, learner="Ada", brain=_brain({}), rng=random.Random(1))
    sid = await run(e)
    row = e.store.one("SELECT arm, decided_by, override FROM activities WHERE session_id=? ORDER BY id LIMIT 1",
                      (sid,))
    assert tuple(row) == ("brain", "default", "brain_unavailable") and summary(e.store, sid)["arm"] == "brain"
