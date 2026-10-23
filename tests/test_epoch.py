"""ADR-0017 §1 epoch: `turn_id` also increments on activity start and end, page turn, correction, learner
adoption and a settings change; anything built under an older epoch is dropped (negotiate's Reobserve)."""

from __future__ import annotations

import anyio

from leafi.study.harness import loop
from leafi.study.harness.identify import adopt
from leafi.study.harness.latch import Terminal
from leafi.study.harness.state import Activity
from tests import seed
from tests.harness_world import make_world


async def _in_group(w, coro):
    latch = w.s.latch
    out = None
    try:
        with anyio.CancelScope() as latch.scope:
            async with anyio.create_task_group() as latch.tg:
                w.inputs.start()
                try:
                    out = await coro()
                finally:
                    latch.tg.cancel_scope.cancel()
    except* Terminal:
        pass
    return out


async def test_activity_start_end_and_a_new_page_read_bump_the_epoch(settings):
    w = make_world(settings, settings, ["The fox ran home.", "It was late and dark."])
    before = w.s.latch.epoch.turn_id
    status = await _in_group(w, lambda: loop.run_activity(w.s, w, Activity("read_listen", {"page": "next"},
                                                                            "default")))
    assert status == "completed"
    e = w.s.latch.epoch
    assert e.turn_id >= before + 3  # start, the page read opened, end
    assert (e.cycle_id, e.page_read_id, e.revision_id) == (w.s.cycle_id, w.read_id, w.rev.id)


async def test_a_correction_bumps_the_epoch(settings):
    w = make_world(settings, settings, ["The fox ran home.", "/fix ran sat", "It was late and dark."])
    seen = []
    orig = w.save_state

    def watch():
        seen.append(w.s.latch.epoch.turn_id)
        orig()

    w.save_state = watch
    await _in_group(w, lambda: loop.run_activity(w.s, w, Activity("read_listen", {"page": "next"}, "default")))
    assert w.rev.rev == 2 and len(set(seen)) >= 2


def test_adoption_bumps_the_epoch_and_reloads_the_settings(settings):
    w = make_world(settings, settings, [])
    ben = seed.learner(w.store, "Ben")
    w.store.execute("UPDATE learners SET settings='{\"autonomy\": 9}', settings_version=4 WHERE id=?", (ben,))
    before = w.s.latch.epoch.turn_id
    assert adopt(w.s, ben)
    e = w.s.latch.epoch
    assert e.turn_id == before + 1 and e.learner_id == ben and e.learner_settings_version == 4
    assert w.s.autonomy == 9
