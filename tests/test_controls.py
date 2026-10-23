"""ADR-0017 §1 controls on the session's task group (`harness/inputs.py`): stop, skip, page turns, lease loss and a
lost Ear, also during playback; demand-driven readers lose nothing and read nothing ahead."""

from __future__ import annotations

import time

import anyio
import pytest

from leafi.core import lease as speech_lease
from leafi.core.hub import Hub
from leafi.core.ports import ListenerLost
from leafi.core.storage import Store
from leafi.core.text import typed_utterance
from leafi.study.harness.inputs import Inputs, StaleInput
from leafi.study.harness.latch import Latch, Terminal
from tests.fakes import FakeMouth, FakeSynth, RecordingFace, ScriptedListener


class TimedListener:
    """Delivers (delay_s, text) items in order; text None raises ListenerLost; then blocks."""

    def __init__(self, items, voice: bool = False) -> None:
        self.items = list(items)
        self.is_voice = voice
        self.reads = 0

    async def next_utterance(self, timeout_s):
        self.reads += 1
        if not self.items:
            await anyio.sleep(3600)
        delay, text = self.items.pop(0)
        await anyio.sleep(delay)
        if text is None:
            raise ListenerLost("microphone unplugged")
        u = typed_utterance(text, "voice" if self.is_voice else "console")
        u.typed = not self.is_voice or text.startswith("/")
        return u

    async def pause(self) -> None: ...

    async def resume(self, after_s: float = 0.0) -> None: ...


async def run_with(inputs: Inputs, body) -> list:
    out: list = []
    latch = inputs.latch
    try:
        with anyio.CancelScope() as latch.scope:
            async with anyio.create_task_group() as latch.tg:
                inputs.start()
                try:
                    await body(inputs, out)
                finally:
                    latch.tg.cancel_scope.cancel()
    except* Terminal:
        out.append("terminal")
    return out


def make(tmp_path, listener, *, control=None, speaking=False, lease=None, face=None) -> Inputs:
    face = face or RecordingFace()
    hub = Hub(faces={"f": face}, mouths={"m": FakeMouth(play_s=3.0)} if speaking else None,
              synthesizer=FakeSynth(tmp_path) if speaking else None, policy="all" if speaking else "none",
              listeners={"main": listener, **({"console": control} if control else {})})
    return Inputs(hub=hub, latch=Latch(), store=Store(tmp_path / "leafi.db"), listener=listener,
                  control_source=control, lease=lease)


async def test_stop_sets_the_latch_and_cancels_the_waiting_listen(tmp_path):
    inputs = make(tmp_path, ScriptedListener(["/stop"]))

    async def body(i, out):
        await i.listen(None)
        out.append("listen returned")

    out = await run_with(inputs, body)
    assert inputs.latch.terminal == "stop" and "listen returned" not in out


async def test_a_listen_timeout_returns_none_and_the_late_utterance_reaches_the_next_listen(tmp_path):
    listener = TimedListener([(0.3, "The fox ran home.")])
    inputs = make(tmp_path, listener)

    async def body(i, out):
        out.append(await i.listen(0.05))
        out.append((await i.listen(2)).text)

    out = await run_with(inputs, body)
    assert out == [None, "The fox ran home."] and listener.reads == 1  # one pending read, not two


async def test_nothing_is_read_ahead_of_demand(tmp_path):
    listener = ScriptedListener(["one", "two", "three"])
    inputs = make(tmp_path, listener)

    async def body(i, out):
        out.append((await i.listen(1)).text)
        await anyio.sleep(0.1)
        out.append(len(listener.script))

    assert await run_with(inputs, body) == ["one", 2]


async def test_a_scripted_timeout_is_a_none(tmp_path):
    inputs = make(tmp_path, ScriptedListener([None, "hello"]))

    async def body(i, out):
        out.append(await i.listen(1))
        out.append((await i.listen(1)).text)

    assert await run_with(inputs, body) == [None, "hello"]


async def test_skip_outside_playback_goes_into_the_queue_once(tmp_path):
    inputs = make(tmp_path, ScriptedListener(["/skip"]))

    async def body(i, out):
        out.append((await i.listen(1)).text)
        out.append(i.latch.take_skip())
        out.append(i.latch.take_skip())

    assert await run_with(inputs, body) == ["/skip", True, False]


async def test_skip_during_playback_cuts_the_line_and_queues_nothing(tmp_path):
    console = TimedListener([(0.2, "/skip")])
    inputs = make(tmp_path, TimedListener([], voice=True), control=console, speaking=True)

    async def body(i, out):
        t0 = time.monotonic()
        await i.say("A long line that plays for three seconds.")
        out.append(time.monotonic() - t0)
        out.append(len(i.latch.skips))

    took, skips = await run_with(inputs, body)
    assert took < 1.5 and skips == 0


async def test_stop_during_playback_silences_and_terminates(tmp_path):
    console = TimedListener([(0.2, "/stop")])
    inputs = make(tmp_path, TimedListener([], voice=True), control=console, speaking=True)

    async def body(i, out):
        await i.say("A long line that plays for three seconds.")
        out.append("finished")

    t0 = time.monotonic()
    out = await run_with(inputs, body)
    assert inputs.latch.terminal == "stop" and "finished" not in out and time.monotonic() - t0 < 1.5


async def test_a_lost_lease_terminates_and_nothing_is_spoken_after_it(tmp_path):
    lease = speech_lease.acquire(tmp_path / "leafi.lock", ttl_s=0.3)
    face = RecordingFace()
    inputs = make(tmp_path, TimedListener([]), lease=lease, face=face)

    async def body(i, out):
        speech_lease._write(lease.path, "someone-else", 60)  # another launch took the lease over
        await i.listen(None)

    await run_with(inputs, body)
    assert inputs.latch.terminal == "lease_lost"
    await inputs.say("See you next time!")  # e.g. deliver's closing line
    assert face.texts[-1] == "See you next time!" and inputs.lease_held() is False
    rows = inputs.store.all("SELECT key, state, reason FROM alert_outbox")
    assert [tuple(r) for r in rows] == [("study-lease", "event", "lease_lost")]


async def test_a_lost_ear_switches_to_the_console_with_a_stale_activity_and_a_new_epoch(tmp_path):
    console = TimedListener([(0.3, "The fox ran home.")])
    inputs = make(tmp_path, TimedListener([(0.05, None)], voice=True), control=console)

    async def body(i, out):
        with pytest.raises(StaleInput):
            await i.listen(2)
        out.append(i.latch.epoch.turn_id)
        out.append((await i.listen(2)).text)
        out.append(i.voice)

    assert await run_with(inputs, body) == [1, "The fox ran home.", False]


async def test_a_lost_ear_without_a_console_ends_the_session(tmp_path):
    inputs = make(tmp_path, TimedListener([(0.05, None)], voice=True))
    inputs.control_source = None

    async def body(i, out):
        await i.listen(2)

    await run_with(inputs, body)
    assert inputs.latch.terminal == "listener_lost_no_console"


async def test_an_eye_page_turn_is_delivered_while_the_page_is_open(tmp_path):
    class Eye:
        async def snapshot(self, _):
            return b"frame"

    class Tracker:
        last = None

        def changed(self, frame):
            return True

        async def settle(self):
            return b"settled"

    listener = TimedListener([])
    inputs = make(tmp_path, listener)
    inputs.hub.eyes = {"e": Eye()}
    inputs.page_tracker, inputs.page_poll_s = Tracker(), 0.02

    async def body(i, out):
        out.append(await i.listen(0.2))  # page closed: no turn
        i.page_open = True
        out.append((await i.listen(1)).text)

    assert await run_with(inputs, body) == [None, "/page"]
