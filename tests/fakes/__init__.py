"""Test doubles with temporal behaviour (testing.md → adapters against fakes)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from leafi.core.ports import AudioClip, Display, Utterance
from leafi.core.text import typed_utterance


class RecordingFace:
    def __init__(self, hang: bool = False) -> None:
        self.shown: list[Display] = []
        self.hang = hang

    async def show(self, msg: Display) -> None:
        if self.hang:
            await asyncio.sleep(3600)
        self.shown.append(msg)

    @property
    def texts(self) -> list[str]:
        return [d.text for d in self.shown if d.kind == "say"]


class FakeMouth:
    """Plays for `play_s` (or forever when `hang`), records start/end, honours stop()."""

    def __init__(self, play_s: float = 0.0, drain_s: float = 0.2, hang: bool = False, fail: bool = False,
                 log: list | None = None, name: str = "mouth") -> None:
        self.play_s = play_s
        self.drain_s = drain_s
        self.hang = hang
        self.fail = fail
        self.log = log if log is not None else []
        self.name = name
        self.played: list[AudioClip] = []
        self.stopped = 0
        self._cancel = asyncio.Event()

    async def play(self, clip: AudioClip) -> None:
        self.log.append(("start", self.name))
        if self.fail:
            raise RuntimeError("speaker broke")
        self.played.append(clip)
        self._cancel.clear()
        try:
            wait = 3600 if self.hang else self.play_s
            try:
                await asyncio.wait_for(self._cancel.wait(), wait)
            except TimeoutError:
                pass
        finally:
            self.log.append(("end", self.name))

    async def stop(self) -> None:
        self.stopped += 1
        self._cancel.set()


class FakeSynth:
    def __init__(self, tmp: Path, fail: bool = False) -> None:
        self.tmp = tmp
        self.fail = fail
        self.calls: list[tuple[str, str, bool]] = []

    async def synth(self, text: str, lang: str, *, slow: bool = False) -> AudioClip:
        self.calls.append((text, lang, slow))
        if self.fail:
            raise RuntimeError("tts down")
        p = self.tmp / f"clip{len(self.calls)}.wav"
        p.write_bytes(b"")
        return AudioClip(p, 0.5, 16000, 1, "wav")


class ScriptedListener:
    """Yields scripted inputs. A string is typed (or voice when `voice=True`); None simulates a timeout;
    an Utterance is passed through. When the script ends it yields `/stop`."""

    def __init__(self, script: list, voice: bool = False, log: list | None = None) -> None:
        self.script = list(script)
        self.is_voice = voice
        self.log = log if log is not None else []
        self.timeouts: list[float | None] = []

    async def next_utterance(self, timeout_s: float | None) -> Utterance | None:
        self.timeouts.append(timeout_s)
        item = self.script.pop(0) if self.script else "/stop"
        if item is None:
            return None
        if isinstance(item, Utterance):
            return item
        u = typed_utterance(item, "script")
        if self.is_voice and not item.startswith("/"):
            u.typed = False
        return u

    async def pause(self) -> None:
        self.log.append(("pause",))

    async def resume(self, after_s: float = 0.0) -> None:
        self.log.append(("resume", after_s))
