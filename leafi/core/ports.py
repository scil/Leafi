"""Capability ports (ADR-0002) and the value types that cross them.

Ports are `typing.Protocol`s; adapters in `leafi.devices` implement any subset. Every port is async.
Audio ownership (overview.md): clips and chunks carry their format; a voice Utterance carries an in-memory
`AudioRef`; a typed Utterance carries none and can never receive a pronunciation score.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from .provenance import SYSTEM, Provenance  # noqa: F401  (re-exported; defined there since M7 design D2)

# ---------------------------------------------------------------- value types


@dataclass(frozen=True)
class Frame:
    """One still image from an Eye. JPEG/PNG bytes; never leaves the LAN."""

    data: bytes
    mime: str = "image/jpeg"
    width: int | None = None
    captured_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class AudioChunk:
    pcm: bytes  # int16 little-endian
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"
    t: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class AudioClip:
    """A playable clip on disk (TTS output). Mouth adapters prepare (pad/transcode) it themselves."""

    path: Path
    duration_s: float
    sample_rate: int = 24000
    channels: int = 1
    codec: str = "wav"  # wav | mp3


@dataclass
class AudioRef:
    """In-memory learner audio for one Utterance; released after the Practice step that may score it."""

    pcm: bytes
    sample_rate: int = 16000
    channels: int = 1

    def release(self) -> None:
        self.pcm = b""


@dataclass(frozen=True)
class Word:
    text: str
    start_s: float | None = None
    end_s: float | None = None
    conf: float | None = None


@dataclass
class Utterance:
    text: str
    words: list[Word]
    typed: bool
    audio_ref: AudioRef | None = None
    line_end: bool = False  # typed line ended with . ? ! or was empty (ADR-0013 completion (ii))
    source: str = "console"

    @property
    def is_voice(self) -> bool:
        return not self.typed


DisplayKind = Literal["say", "status", "listening", "alert"]


@dataclass(frozen=True)
class Display:
    kind: DisplayKind
    text: str
    lang: str = "en"


@dataclass(frozen=True)
class PresenceEvent:
    camera: str
    label: str
    t: float


class ListenerLost(RuntimeError):
    """The selected Ear stopped delivering audio (device unplugged, driver error, capture ended). Raised by a
    voice Listener's `next_utterance`; the session answers with `LISTENER_LOST` (flows/reading-session.md)."""


# ---------------------------------------------------------------- ports


@runtime_checkable
class Eye(Protocol):
    async def snapshot(self, max_width: int | None = None) -> Frame | None: ...


@runtime_checkable
class Ear(Protocol):
    def listen(self) -> AsyncIterator[AudioChunk]: ...  # 16 kHz mono int16


@runtime_checkable
class Mouth(Protocol):
    drain_s: float  # read once by the listening gate after play()

    async def play(self, clip: AudioClip) -> None: ...  # returns at the estimated playback end

    async def stop(self) -> None: ...  # cancel current playback


@runtime_checkable
class Face(Protocol):
    async def show(self, msg: Display) -> None: ...


@runtime_checkable
class Listener(Protocol):
    is_voice: bool

    async def next_utterance(self, timeout_s: float | None) -> Utterance | None: ...  # None = timeout

    async def pause(self) -> None: ...  # discard buffered audio

    async def resume(self, after_s: float = 0.0) -> None: ...


@runtime_checkable
class Presence(Protocol):
    def subscribe(self, fn: Callable[[PresenceEvent], None]) -> Callable[[], None]: ...




@dataclass(frozen=True)
class Counts:
    """The parent notification (M5 design D5): who read and how much, nothing else. The notifier renders it
    through `leafi.privacy`, which names the learner by their surrogate only when they may be named."""

    learner_id: int | None
    session_id: int | None
    pages: int = 0
    words_read: int = 0
    to_practise: int = 0
    new_items: int = 0


@runtime_checkable
class Notifier(Protocol):
    async def notify(self, counts: Counts) -> None: ...  # counts only (ADR-0011, M5 D5): no text, no frame


@runtime_checkable
class Synthesizer(Protocol):
    """Implemented by `leafi.services.tts`; injected into the Hub by the composition root."""

    async def synth(self, text: str, lang: str, *, slow: bool = False, provenance: Provenance = SYSTEM
                    ) -> AudioClip: ...
    # provenance: a learner's own words, or any line holding a protected name, never reach a cloud backend
    # while PRIVACY_TTS_LEARNER_LINES=local (M5 D13).
