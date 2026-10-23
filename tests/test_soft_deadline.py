"""ADR-0017 §2, §6.3: no new boundary activity after the soft deadline; a continuation during grace runs only
with `session.end_mode = finish_activity`."""

from __future__ import annotations

import time

from leafi.core.storage import Store
from leafi.study.harness import settings as hs
from tests import seed
from tests.fakes import ScriptedListener
from tests.harness_session import activities, env, run


class SoftAt(ScriptedListener):
    """Moves the soft deadline into the past just before the reply at index `at` is read."""

    def __init__(self, script, at: int) -> None:
        super().__init__(script)
        self.at, self.n, self.s = at, 0, None

    async def next_utterance(self, timeout_s):
        if self.n == self.at:
            self.s.soft_deadline = time.monotonic() - 1
        self.n += 1
        return await super().next_utterance(timeout_s)


def _env(settings, listener, end_mode="finish_activity"):
    store = Store(settings.db_path)
    ada = seed.learner(store, "Ada")
    hs.save(store, ada, {"session.end_mode": end_mode})
    e = env(settings, [], listener=listener, learner="Ada")
    e.on_built = lambda s, w: setattr(listener, "s", s)
    return e


async def test_an_activity_confirmed_after_the_soft_deadline_does_not_start(settings):
    lst = SoftAt([None, "/stop"], at=0)  # the deadline passes while Leafi waits for the answer to its offer
    e = _env(settings, lst)
    sid = await run(e)
    assert activities(e.store, sid) == []  # §2: `if now >= s.soft_deadline: break` before run_activity
    from tests.harness_session import summary

    assert summary(e.store, sid)["end"] == "end"  # a normal end, not a terminal


async def test_a_continuation_during_grace_runs_with_finish_activity(settings, tmp_path):
    p2 = tmp_path / "p2.txt"
    p2.write_text("The moon was up.", encoding="utf-8")
    lst = SoftAt([None, "The fox ran home.", f"/page 2 --text {p2}", "The moon was up.", "/stop"], at=2)
    e = _env(settings, lst)
    sid = await run(e)
    assert activities(e.store, sid)[:2] == [("read_listen", "page_turned", False), ("read_listen", "completed", True)]


async def test_no_continuation_during_grace_with_hard(settings, tmp_path):
    p2 = tmp_path / "p2.txt"
    p2.write_text("The moon was up.", encoding="utf-8")
    lst = SoftAt([None, "The fox ran home.", f"/page 2 --text {p2}", "/stop"], at=2)
    e = _env(settings, lst, end_mode="hard")
    sid = await run(e)
    kinds = activities(e.store, sid)
    assert kinds[0] == ("read_listen", "page_turned", False) and not any(c for _, _, c in kinds)
