"""ADR-0017 §6.3 session length: by age band, guests and unknown ages have their own settings; `finish_activity`
lets the running activity finish within grace; `hard` cuts it."""

from __future__ import annotations

import datetime as dt
import time

from leafi.core.storage import Store
from leafi.study.harness import settings as hs
from tests import seed
from tests.fakes import ScriptedListener
from tests.harness_session import activities, env, run

TODAY = dt.date(2026, 10, 23)


def test_length_by_kind_and_age():
    assert hs.LearnerSettings({}, kind="guest").session_max_min(TODAY) == 15
    assert hs.LearnerSettings({"session.max_min_guest": 10}, kind="guest").session_max_min(TODAY) == 10
    assert hs.LearnerSettings({}).session_max_min(TODAY) == 15  # unknown age
    assert hs.LearnerSettings({"session.max_min_unknown_age": 12}).session_max_min(TODAY) == 12
    assert hs.LearnerSettings({}, birth_year=2019).session_max_min(TODAY) == 15  # age 7
    assert hs.LearnerSettings({}, birth_year=2016).session_max_min(TODAY) == 20  # age 10
    assert hs.LearnerSettings({"session.max_min": 30}, birth_year=2016).session_max_min(TODAY) == 30


class DeadlineAt(ScriptedListener):
    def __init__(self, script, at: int, which: str) -> None:
        super().__init__(script)
        self.at, self.n, self.s, self.which = at, 0, None, which

    async def next_utterance(self, timeout_s):
        if self.n == self.at:
            past = time.monotonic() - 1
            self.s.soft_deadline = past
            if self.which == "hard":
                self.s.latch.hard_deadline = past
                import anyio

                await anyio.sleep(1)  # the watcher polls every 0.25 s; the learner is mid-sentence meanwhile
        self.n += 1
        return await super().next_utterance(timeout_s)


async def _run(settings, mode: str, which: str):
    store = Store(settings.db_path)
    ada = seed.learner(store, "Ada")
    hs.save(store, ada, {"session.end_mode": mode})
    lst = DeadlineAt([None, "The fox ran home.", "It was late and dark.", "/stop"], at=2, which=which)
    e = env(settings, [], listener=lst, learner="Ada")
    e.on_built = lambda s, w: setattr(lst, "s", s)
    return e, await run(e)


async def test_finish_activity_lets_the_running_reading_finish_within_grace(settings):
    e, sid = await _run(settings, "finish_activity", "soft")
    assert activities(e.store, sid) == [("read_listen", "completed", False)]  # finished, then nothing new starts


async def test_hard_cuts_the_running_activity(settings):
    e, sid = await _run(settings, "hard", "hard")
    assert activities(e.store, sid) == [("read_listen", "time_up_session", False)]
