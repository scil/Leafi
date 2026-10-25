"""Several typed sources (ADR-0017 §1 as amended 2026-10-25; session panel design D2, step 3): one reader per typed
source beside the main one, the main source tracked by name, and a source that is not `main_capable` (the session
panel) never leads: not as the study listener, not after a lost Ear. Real Store and Inputs; nothing speaks."""

from __future__ import annotations

import anyio
import pytest

from leafi.core.hub import DevicesConfig, DeviceSpec, Hub
from leafi.core.ports import ListenerLost, Utterance
from leafi.core.storage import Store
from leafi.core.text import typed_utterance
from leafi.devices.console import ConsoleDevice
from leafi.study.harness.inputs import Inputs
from leafi.study.harness.latch import Latch, Terminal
from tests.fakes import RecordingFace


class Typed:
    """A typed source: its lines, each after `delay_s`, then quiet."""

    is_voice = False

    def __init__(self, lines, name: str, *, delay_s: float = 0.0, main_capable: bool = True) -> None:
        self.lines, self.name, self.delay_s, self.main_capable = list(lines), name, delay_s, main_capable

    async def next_utterance(self, timeout_s) -> Utterance | None:
        if not self.lines:
            await anyio.sleep_forever()
        await anyio.sleep(self.delay_s)
        return typed_utterance(self.lines.pop(0), self.name)

    async def pause(self) -> None: ...

    async def resume(self, after_s: float = 0.0) -> None: ...


def panel(lines=(), **kw) -> Typed:
    return Typed(lines, "panel", main_capable=False, **kw)


class LostEar:
    """A voice Ear that is lost at its first read."""

    is_voice = True

    async def next_utterance(self, timeout_s):
        await anyio.sleep(0.01)
        raise ListenerLost("microphone unplugged")

    async def pause(self) -> None: ...

    async def resume(self, after_s: float = 0.0) -> None: ...


def make(tmp_path, main, *sources) -> Inputs:
    hub = Hub(faces={"f": RecordingFace()}, policy="none",
              listeners={"main": main, **{getattr(s, "name", str(i)): s for i, s in enumerate(sources)}})
    return Inputs(hub=hub, latch=Latch(), store=Store(tmp_path / "leafi.db"), listener=main)


async def drive(inputs: Inputs, body) -> None:
    try:
        with anyio.CancelScope() as inputs.latch.scope:
            async with anyio.create_task_group() as inputs.latch.tg:
                inputs.start()
                try:
                    with anyio.fail_after(5):
                        await body(inputs)
                finally:
                    inputs.latch.tg.cancel_scope.cancel()
    except* Terminal:
        pass


async def test_every_typed_source_gets_a_reader_and_the_first_answer_wins(tmp_path):
    console = Typed(["home"], "console")
    inputs = make(tmp_path, Typed([], "keyboard"), console, panel(["den"], delay_s=0.05))
    assert [s.name for s in inputs.control_sources] == ["console", "panel"]  # beside the main one
    got = []

    async def body(i):
        got.append((await i.listen(2, ("act", 1, "q0"))).text)
        await anyio.sleep(0.1)  # the panel's line arrives, still owned by q0
        got.append(await i.listen(0.2, ("act", 1, "q1")))  # q0 has ended: its second answer is dropped

    await drive(inputs, body)
    assert got == ["home", None]


async def test_a_lost_ear_is_replaced_by_the_console_never_by_the_panel(tmp_path):
    inputs = make(tmp_path, LostEar(), panel(["/skip"], delay_s=1.0), Typed(["The fox ran home."], "console",
                                                                            delay_s=0.1))
    got = []

    async def body(i):
        try:
            await i.listen(2)
        except Exception as e:  # the switch ends an unowned listen (D21): the caller retries
            got.append(type(e).__name__)
        got.append((await i.listen(2)).text)

    await drive(inputs, body)
    assert inputs.latch.terminal is None
    assert inputs.listener.name == "console" and inputs.main_name == "control:console"
    assert got == ["StaleInput", "The fox ran home."]


async def test_a_lost_ear_with_only_the_panel_ends_the_session(tmp_path):
    inputs = make(tmp_path, LostEar(), panel())

    async def body(i):
        await i.listen(2)

    await drive(inputs, body)
    assert inputs.latch.terminal == "listener_lost_no_console"


async def test_only_the_main_sources_silence_is_a_timeout(tmp_path):
    class Silent(Typed):
        async def next_utterance(self, timeout_s):
            return None

    inputs = make(tmp_path, Typed(["late"], "console", delay_s=0.1), Silent([], "panel", main_capable=False))

    async def body(i):
        assert (await i.listen(2)).text == "late"  # the panel's None is no timeout

    await drive(inputs, body)


def test_the_hub_never_picks_the_panel_as_the_study_listener():
    p, c = panel(), Typed([], "console")
    assert Hub(listeners={"panel": p, "console": c}).listener() is c
    assert Hub(listeners={"panel": p, "console": c}, study_listener="panel").listener() is c
    with pytest.raises(LookupError):
        Hub(listeners={"panel": p}).listener()


def test_the_composition_root_adds_the_console_beside_a_panel_and_keeps_it_main(settings):
    from leafi import app

    p = panel()
    built = app.build(settings, config=DevicesConfig(devices=[]), text_mode=True, extra={"listener": {"panel": p}})
    assert built.hub.study_listener == "console" and isinstance(built.hub.listener(), ConsoleDevice)
    assert built.hub.listeners["panel"] is p
    cfg = DevicesConfig(devices=[DeviceSpec("console", "console", ["listener", "face"])])
    built = app.build(settings, config=cfg, text_mode=True, extra={"listener": {"panel": p}})
    assert built.hub.listener() is built.devices["console"]  # whatever the order of the slots


async def test_the_consoles_end_of_input_stops_unless_told_not_to():
    assert (await ConsoleDevice(lines=[]).next_utterance(None)).text == "/stop"
    quiet = ConsoleDevice(lines=[], options={"eof_stops": False})
    with anyio.move_on_after(0.2) as scope:
        await quiet.next_utterance(None)
    assert scope.cancelled_caught
