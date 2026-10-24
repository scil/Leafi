"""The filler (ADR-0017 §5; M7 design D12): Faces show "…" and the PC Mouth says one line past 0.8 s; nothing when
the call is quick, nothing after the epoch changed, and a filler error never fails the call."""

from __future__ import annotations

import anyio

from leafi.study.brain.filler import with_filler


async def _call(seconds: float, value="ok"):
    await anyio.sleep(seconds)
    return value


async def test_a_slow_call_gets_the_filler_and_a_quick_one_does_not():
    shown, said = [], []

    async def show(d):
        shown.append(d.text)

    async def say(t):
        said.append(t)

    assert await with_filler(_call(0.3), show=show, say=say, epoch=lambda: (1,), after_s=0.1) == "ok"
    assert shown == ["…"] and len(said) == 1
    shown.clear(), said.clear()
    await with_filler(_call(0.01), show=show, say=say, epoch=lambda: (1,), after_s=0.1)
    assert shown == [] and said == []


async def test_no_filler_after_the_epoch_changed_and_an_error_never_fails_the_call():
    epoch = [1]

    async def show(d):
        raise RuntimeError("face gone")

    async def bump_then_call():
        epoch[0] = 2
        return await _call(0.3)

    assert await with_filler(bump_then_call(), show=show, say=None, epoch=lambda: (epoch[0],), after_s=0.1) == "ok"
    assert await with_filler(_call(0.3), show=show, say=None, epoch=lambda: (1,), after_s=0.1) == "ok"  # error logged
