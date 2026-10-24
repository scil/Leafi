"""ASR service and the voice Listener composition (Ear + VAD + ASR → Utterances).

Backends: `sherpa` (sherpa-onnx Parakeet TDT v2 int8, local, lazy) and `mock`. `whisper` is named in the
config docs but not written in v1. Hotword biasing stays off (`ASR_HOTWORDS=off`, ADR-0011); prototype P-1
recorded that it works per stream with a `bpe.vocab` (see `sherpa.py`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from leafi.core.ports import AudioChunk, AudioRef, Ear, ListenerLost, Utterance, Word
from leafi.services._registry import Registry

log = logging.getLogger("leafi.asr")

REGISTRY = Registry("asr", {"sherpa": "leafi.services.asr.sherpa", "mock": "leafi.services.asr.mock"},
                    deferred={"whisper"})
HOTWORDS_MODES = ("off", "lexicon")  # ASR_HOTWORDS values; sherpa treats anything but "off" as on


class Recognizer(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int, hotwords: list[str] | None = None) -> list[Word]: ...


class Vad(Protocol):
    """Speech segmenter over int16 PCM (`services/asr/vad.py` wraps Silero through sherpa-onnx). Each segment
    comes with `end_t`, the monotonic time of its last voiced sample mapped onto the fed chunks' `t` (M7 design
    D21), or None when unknown."""

    def feed(self, pcm: bytes, t: float | None = None) -> list[tuple[bytes, float | None]]: ...

    def flush(self) -> list[tuple[bytes, float | None]]: ...

    def reset(self) -> None: ...


def rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    import array

    a = array.array("h", pcm[: len(pcm) - len(pcm) % 2])
    return (sum(x * x for x in a) / max(1, len(a))) ** 0.5


class VoiceListener:
    """End-pointing over an Ear; one Utterance per stretch of speech.

    With a `vad` the segments come from Silero (P-6/S3); without one the energy rule applies: speech above
    `threshold` followed by `pause_s` of silence. The contract is the same either way: `pause()` discards
    buffered audio, `resume(after_s)` reopens capture after the Mouths' drain, and a capture failure in the
    Ear surfaces once as `ListenerLost` from `next_utterance` (TD-16) instead of an endless `None`.
    """

    is_voice = True

    def __init__(self, ear: Ear, recognizer: Recognizer, *, pause_s: float = 1.2, threshold: float = 500.0,
                 vad: Vad | None = None, clock=time.monotonic) -> None:
        self.ear = ear
        self.recognizer = recognizer
        self.pause_s = pause_s
        self.threshold = threshold
        self.vad = vad
        self._clock = clock
        self._open_at = 0.0
        self._paused = False
        self._queue: asyncio.Queue[AudioChunk] | None = None
        self._pump_task: asyncio.Task | None = None
        self._segments: list[tuple[bytes, float | None]] = []
        self._pause_gen = 0  # bumped by pause(): speech cut by Leafi's line never closes after the resume
        self._recognising: asyncio.Future[Utterance] | None = None
        self.lost: BaseException | None = None
        self._lost_reported = False

    def _ensure_pump(self) -> asyncio.Queue:
        """Capture runs in one persistent task; input deadlines apply to queue reads only, so a timeout never
        closes the Ear's iterator (review 1 #8)."""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=600)
            self._pump_task = asyncio.create_task(self._pump())
        return self._queue

    async def _pump(self) -> None:
        q = self._queue
        try:
            async for chunk in self.ear.listen():
                if not self._gate_open():
                    continue  # Leafi is speaking or draining: discard
                if q.full():
                    q.get_nowait()
                    log.warning("capture overflow: dropped one chunk")
                q.put_nowait(chunk)
            self.lost = ListenerLost("capture ended")
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # noqa: BLE001 - any capture failure is reported, never swallowed (TD-16)
            log.error("capture failed: %s", e)
            self.lost = e if isinstance(e, ListenerLost) else ListenerLost(f"{type(e).__name__}: {e}")

    async def close(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()

    async def pause(self) -> None:
        self._paused = True
        if self._queue is not None:  # discard buffered audio
            while not self._queue.empty():
                self._queue.get_nowait()
        self._segments.clear()
        self._pause_gen += 1
        if self.vad is not None:
            self.vad.reset()

    async def resume(self, after_s: float = 0.0) -> None:
        self._open_at = self._clock() + after_s
        self._paused = False

    def _gate_open(self) -> bool:
        return not self._paused and self._clock() >= self._open_at

    def _raise_if_lost(self, q: asyncio.Queue) -> None:
        if self.lost is not None and q.empty() and not self._segments:
            if self._lost_reported:
                raise ListenerLost("listener already lost")
            self._lost_reported = True
            raise self.lost

    async def next_utterance(self, timeout_s: float | None) -> Utterance | None:
        # A segment in the recognizer outlives a cancelled read: the session cancels a timed read when its
        # window (SENTENCE_PAUSE_S) ends, and Parakeet's first call alone takes longer than that (model load),
        # so the speech is kept in `_recognising` and the next read delivers it.
        if self._recognising is None:
            q = self._ensure_pump()
            seg = await (self._segment_vad(q, timeout_s) if self.vad is not None
                         else self._segment_energy(q, timeout_s))
            if seg is None:
                return None
            self._recognising = asyncio.ensure_future(self._recognise(*seg))
        u = await asyncio.shield(self._recognising)
        self._recognising = None
        return u

    async def _recognise(self, pcm: bytes, ended_at: float | None) -> Utterance:
        words = await self.recognizer.transcribe(pcm, 16000)
        return Utterance(" ".join(w.text for w in words), words, typed=False, audio_ref=AudioRef(pcm), source="voice",
                         ended_at=ended_at)  # set at segment close, before recognition (D21)

    async def _next_chunk(self, q: asyncio.Queue, remaining: float | None) -> AudioChunk | None:
        """One chunk, or None on the caller's deadline; raises ListenerLost once the pump has died dry."""
        while True:
            self._raise_if_lost(q)
            try:
                return await asyncio.wait_for(q.get(), remaining if remaining is None else max(0.05, remaining))
            except TimeoutError:
                if self._pump_task is not None and self._pump_task.done():
                    continue  # let _raise_if_lost report it
                return None

    async def _segment_vad(self, q: asyncio.Queue, timeout_s: float | None) -> tuple[bytes, float | None] | None:
        loop = asyncio.get_running_loop()
        deadline = None if timeout_s is None else loop.time() + timeout_s
        while True:
            if self._segments:
                return self._segments.pop(0)
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                return None
            chunk = await self._next_chunk(q, remaining)
            if chunk is None:
                return None
            if not self._gate_open():
                self.vad.reset()
                continue
            self._segments.extend(self.vad.feed(chunk.pcm, chunk.t))

    async def _segment_energy(self, q: asyncio.Queue, timeout_s: float | None) -> tuple[bytes, float] | None:
        """(pcm, ended_at): `ended_at` is the `t` of the last above-threshold chunk, not of the chunk that closed
        the segment `pause_s` later (D21)."""
        speech: list[bytes] = []
        silence_s, voiced_t = 0.0, 0.0
        gen = self._pause_gen
        loop = asyncio.get_running_loop()
        deadline = None if timeout_s is None else loop.time() + timeout_s
        while True:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0 and not speech:
                return None
            chunk = await self._next_chunk(q, remaining if not speech else None)
            if chunk is None:
                return None
            if not self._gate_open() or gen != self._pause_gen:  # Leafi spoke since this speech began
                speech.clear()
                gen = self._pause_gen
                if not self._gate_open():
                    continue
            secs = len(chunk.pcm) / (2 * chunk.sample_rate)
            if rms(chunk.pcm) >= self.threshold:
                speech.append(chunk.pcm)
                silence_s, voiced_t = 0.0, chunk.t
            elif speech:
                speech.append(chunk.pcm)
                silence_s += secs
                if silence_s >= self.pause_s:
                    return b"".join(speech), voiced_t
