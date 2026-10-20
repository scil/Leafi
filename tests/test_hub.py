"""Hub, voice policy, listening gate and devices.yml parsing (ADR-0002, device-routing.md)."""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys

import pytest

from leafi.core.hub import DevicesConfigError, Hub, ListeningGate, parse_devices_config
from leafi.devices.console import ConsoleDevice
from tests.fakes import FakeMouth, FakeSynth, RecordingFace, ScriptedListener


def hub_with(tmp_path, mouths=None, policy="all", synth=None, faces=None, **kw) -> Hub:
    return Hub(mouths=mouths or {}, faces=faces if faces is not None else {"f": RecordingFace()},
               synthesizer=synth if synth is not None else FakeSynth(tmp_path), policy=policy, **kw)


async def test_say_with_zero_mouths_shows_text_and_returns(tmp_path):
    synth = FakeSynth(tmp_path)
    hub = hub_with(tmp_path, synth=synth)
    drain = await hub.say("Nice reading!")
    assert hub.faces["f"].texts == ["Nice reading!"]
    assert drain == 0.0
    assert synth.calls == []


async def test_say_with_one_and_two_mouths_plays_each_and_returns_max_drain(tmp_path):
    one = FakeMouth(drain_s=0.2)
    hub = hub_with(tmp_path, {"cam": one})
    assert await hub.say("hi") == 0.2
    assert len(one.played) == 1
    a, b = FakeMouth(drain_s=0.6), FakeMouth(drain_s=0.2)
    hub2 = hub_with(tmp_path, {"cam": a, "pc": b})
    assert await hub2.say("hi") == 0.6
    assert len(a.played) == 1 and len(b.played) == 1


async def test_policy_primary_and_none(tmp_path):
    a, b = FakeMouth(), FakeMouth()
    hub = hub_with(tmp_path, {"cam": a, "pc": b}, policy="primary", primary_mouth="pc")
    await hub.say("hi")
    assert (len(a.played), len(b.played)) == (0, 1)
    synth = FakeSynth(tmp_path)
    hub_none = hub_with(tmp_path, {"cam": FakeMouth()}, policy="none", synth=synth)
    await hub_none.say("hi")
    assert synth.calls == [] and hub_none.faces["f"].texts == ["hi"]


async def test_say_tts_failure_shows_text_and_returns(tmp_path):
    mouth = FakeMouth()
    hub = hub_with(tmp_path, {"cam": mouth}, synth=FakeSynth(tmp_path, fail=True))
    assert await hub.say("Let's try that word once more.") == 0.0
    assert hub.faces["f"].texts == ["Let's try that word once more."]
    assert mouth.played == []


async def test_failing_mouth_never_raises(tmp_path):
    hub = hub_with(tmp_path, {"cam": FakeMouth(fail=True), "pc": FakeMouth()})
    await hub.say("still fine")


async def test_hung_face_does_not_block_say(tmp_path):
    hub = hub_with(tmp_path, {"pc": FakeMouth()}, faces={"hung": RecordingFace(hang=True), "ok": RecordingFace()},
                   face_timeout_s=0.05)
    await asyncio.wait_for(hub.say("hello"), 2)
    assert hub.faces["ok"].texts == ["hello"]


async def test_slow_mouth_past_say_timeout_is_cancelled(tmp_path):
    hung = FakeMouth(hang=True)
    hub = hub_with(tmp_path, {"cam": hung}, say_timeout_s=0.1)
    await asyncio.wait_for(hub.say("long line"), 2)
    assert hung.stopped >= 1


async def test_concurrent_say_is_serialised(tmp_path):
    log: list = []
    m = FakeMouth(play_s=0.05, log=log)
    hub = hub_with(tmp_path, {"pc": m})
    await asyncio.gather(hub.say("one"), hub.say("two"))
    assert log == [("start", "mouth"), ("end", "mouth"), ("start", "mouth"), ("end", "mouth")]


async def test_stop_during_playback_cancels_current_and_clears_queue(tmp_path):
    m = FakeMouth(hang=True)
    hub = hub_with(tmp_path, {"pc": m})
    first = asyncio.create_task(hub.say("one"))
    second = asyncio.create_task(hub.say("two"))
    await asyncio.sleep(0.05)
    await hub.stop_speaking()
    await asyncio.wait_for(asyncio.gather(first, second), 2)
    assert m.stopped >= 1
    assert len(m.played) == 1  # the queued line was dropped


async def test_listening_gate_pauses_during_playback_and_reopens_after_drain(tmp_path):
    log: list = []
    listener = ScriptedListener([], log=log)
    hub = hub_with(tmp_path, {"cam": FakeMouth(drain_s=0.6, log=log), "pc": FakeMouth(drain_s=0.2, log=log)})
    gate = ListeningGate(listener)
    await gate.speak(hub, "hello")
    assert log[0] == ("pause",)
    assert log[-1] == ("resume", 0.6)
    assert all(e[0] in ("start", "end") for e in log[1:-1])
    assert gate.is_open


# ---------------------------------------------------------------- devices.yml

ENV = {"GO2RTC_URL": "http://127.0.0.1:2984", "STREAM_NAME": "cam_xiaomi"}


def _cfg(devices, **top):
    return {"version": 1, "devices": devices, **top}


def test_missing_required_var_disables_device_with_warning():
    cfg = parse_devices_config(_cfg([
        {"name": "desk_cam", "adapter": "go2rtc_camera", "capabilities": ["eye", "mouth"],
         "options": {"go2rtc_url": "${GO2RTC_URL}", "src_dir": "${SPEAKER_SRC_DIR}"}},
        {"name": "console", "adapter": "console", "capabilities": ["listener", "face"]},
    ]), ENV.get)
    cam = cfg.devices[0]
    assert cam.disabled and "SPEAKER_SRC_DIR" in cam.disabled
    assert [d.name for d in cfg.enabled()] == ["console"]
    assert any("desk_cam" in w for w in cfg.warnings)


def test_optional_var_default_and_expansion():
    cfg = parse_devices_config(_cfg([
        {"name": "n", "adapter": "notifier", "capabilities": ["notifier"],
         "options": {"bark_url": "${BARK_URL:-}", "url": "${GO2RTC_URL}/x"}}]), ENV.get)
    assert cfg.devices[0].options == {"bark_url": "", "url": "http://127.0.0.1:2984/x"}
    assert cfg.devices[0].disabled is None


def test_unknown_adapter_or_capability_is_a_startup_error_naming_the_device():
    with pytest.raises(DevicesConfigError, match="toaster"):
        parse_devices_config(_cfg([{"name": "toaster", "adapter": "nope", "capabilities": []}]), ENV.get,
                             known_adapters={"console"})
    with pytest.raises(DevicesConfigError, match="kettle"):
        parse_devices_config(_cfg([{"name": "kettle", "adapter": "console", "capabilities": ["smell"]}]), ENV.get)


def test_checked_in_devices_yml_parses_with_known_adapters(settings, monkeypatch):
    from leafi import app

    monkeypatch.setattr(settings, "devices_file", __import__("pathlib").Path("config/devices.yml"))
    cfg = app.load_config(settings)
    names = {d.name for d in cfg.devices}
    assert {"desk_cam", "pc", "console", "parent_phone"} <= names
    assert cfg.study_eye == "desk_cam"


def test_build_text_mode_has_console_listener_and_no_mouth_speech(settings, tmp_path):
    from leafi import app
    from leafi.core.hub import DevicesConfig, DeviceSpec

    cfg = DevicesConfig(devices=[DeviceSpec("console", "console", ["listener", "face"])])
    built = app.build(settings, config=cfg, text_mode=True)
    assert built.hub.policy == "none"
    assert built.hub.listener() is built.devices["console"]


# ---------------------------------------------------------------- console + purity


async def test_console_device_echoes_and_reads_scripted_lines():
    out = io.StringIO()
    con = ConsoleDevice(lines=["The dog ran.", ""], stdout=out)
    u = await con.next_utterance(None)
    assert u.text == "The dog ran." and u.typed and u.line_end and u.audio_ref is None
    assert [w.text for w in u.words] == ["The", "dog", "ran"]
    assert (await con.next_utterance(None)).line_end  # empty line ends a sentence
    assert (await con.next_utterance(None)).text == "/stop"  # end of input
    from leafi.core.ports import Display

    await con.show(Display("say", "Hello"))
    assert "Leafi: Hello" in out.getvalue()


def test_import_is_pure():
    """Importing every adapter and service module opens no socket and loads no heavy package."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    mods = []
    for f in sorted((root / "leafi").rglob("*.py")):
        rel = f.relative_to(root).with_suffix("")
        if rel.name == "__main__":
            continue
        parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
        mods.append(".".join(parts))
    code = (
        "import importlib, socket, sys\n"
        "def deny(*a, **k): raise SystemExit('socket opened at import time')\n"
        "socket.socket.connect = deny\n"
        f"for m in {mods!r}: importlib.import_module(m)\n"
        "heavy = ['sounddevice','sherpa_onnx','kokoro_onnx','rapidocr','openpronounce','anthropic','edge_tts',"
        "'onnxruntime','torch','zxingcpp']\n"
        "print(','.join(m for m in heavy if m in sys.modules))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


async def test_local_only_flag_reaches_the_synthesizer_and_failure_still_shows_text(tmp_path):
    class Synth(FakeSynth):
        async def synth(self, text, lang, *, slow=False, local_only=False):
            self.calls.append((text, lang, local_only))
            raise RuntimeError("no local backend")

    synth = Synth(tmp_path)
    hub = hub_with(tmp_path, {"cam": FakeMouth()}, synth=synth)
    await hub.say("Thanks! Zorblat it is.", local_only=True)
    assert synth.calls == [("Thanks! Zorblat it is.", "en", True)]
    assert hub.faces["f"].texts == ["Thanks! Zorblat it is."]


async def test_cancelling_say_stops_the_mouth_before_listening_reopens(tmp_path):
    """Review 1 #6: cancellation of a speaking task must stop playback and drain before the gate reopens."""
    log: list = []
    mouth = FakeMouth(hang=True, drain_s=0.6, log=log)
    listener = ScriptedListener([], log=log)
    hub = hub_with(tmp_path, {"cam": mouth})
    gate = ListeningGate(listener)
    task = asyncio.create_task(gate.speak(hub, "a long line"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mouth.stopped >= 1
    assert ("end", "mouth") in log
    assert log.index(("end", "mouth")) < log.index(("resume", 0.6))
    assert not hub._play_tasks and not hub._lock.locked()


async def test_concurrent_speech_keeps_the_gate_closed_until_the_last_line_drains(tmp_path):
    """Review 1 #9: pause/speak/drain/resume is one serialised operation."""
    log: list = []
    listener = ScriptedListener([], log=log)
    hub = hub_with(tmp_path, {"pc": FakeMouth(play_s=0.05, drain_s=0.2, log=log)})
    gate = ListeningGate(listener)
    await asyncio.gather(gate.speak(hub, "one"), gate.speak(hub, "two"))
    assert log == [("pause",), ("start", "mouth"), ("end", "mouth"), ("resume", 0.2),
                   ("pause",), ("start", "mouth"), ("end", "mouth"), ("resume", 0.2)]
