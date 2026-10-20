"""Turn-scoped async guard (ADR-0010 §5/§8): a stale Brain result is rejected."""

from __future__ import annotations

from leafi.services.brain.mock import MockBrain
from leafi.study import coach


async def test_stale_brain_result_is_discarded_by_the_turn_guard():
    guard = coach.AsyncGuard(7)
    guard.update(3, 1)

    class Slow(MockBrain):
        async def run(self, req):
            guard.update(3, 2)  # the learner skipped meanwhile
            return await super().run(req)

    assert await coach.enrich(Slow(), coach.questions_request("The fox ran.", []), guard, 1.0) is None
    guard2 = coach.AsyncGuard(7)
    assert await coach.enrich(MockBrain(), coach.questions_request("The fox ran.", []), guard2, 1.0)
