"""ASR service and the voice Listener composition (Ear + VAD + ASR → Utterances).

Backends: `sherpa` (sherpa-onnx Parakeet TDT v2 int8, local, lazy) and `mock`. `whisper` is named in the
config docs but not written in v1. Hotword biasing stays off (`ASR_HOTWORDS=off`, ADR-0011) and the
sherpa backend raises NotImplementedError for it until prototype P-1 records whether it works.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from leafi.core.ports import AudioChunk, AudioRef, Ear, Utterance, Word
from leafi.services._registry import Registry

log = logging.getLogger("leafi.asr")

REGISTRY = Registry("asr", {"sherpa": "leafi.services.asr.sherpa", "mock": "leafi.services.asr.mock"},
                    deferred={"whisper"})


class Recognizer(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int, hotwords: list[str] | None = None) -> list[Word]: ...


def rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    import array

    a = array.array("h", pcm[: len(pcm) - len(pcm) % 2])
    return (sum(x * x for x in a) / max(1, len(a))) ** 0.5


class VoiceListener:
    """Energy end-pointing over an Ear; one Utterance per stretch of speech followed by `pause_s` silence.

    Silero VAD replaces the energy rule in S3 (P-6); the contract stays: `pause()` discards buffered audio,
    `resume(after_s)` reopens capture after the Mouths' drain.
    """

    is_voice = True

    def __init__(self, ear: Ear, recognizer: Recognizer, *, pause_s: float = 1.2, threshold: float = 500.0,
                 clock=time.monotonic) -> None:
        self.ear = ear
        self.recognizer = recognizer
        self.pause_s = pause_s
        self.threshold = threshold
        self._clock = clock
        self._open_at = 0.0
        self._paused = False
        self._queue: asyncio.Queue[AudioChunk] | None = None
        self._pump_task: asyncio.Task | None = None

    def _ensure_pump(self) -> asyncio.Queue:
        """Capture runs in one persistent task; input deadlines apply to queue reads only, so a timeout never
        closes the Ear's iterator (review 1 #8)."""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=600)
            self._pump_task = asyncio.create_task(self._pump())
        return self._queue

    async def _pump(self) -> None:
        q = self._queue
        async for chunk in self.ear.listen():
            if not self._gate_open():
                continue  # Leafi is speaking or draining: discard
            if q.full():
                q.get_nowait()
                log.warning("capture overflow: dropped one chunk")
            q.put_nowait(chunk)

    async def close(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()

    async def pause(self) -> None:
        self._paused = True
        if self._queue is not None:  # discard buffered audio
            while not self._queue.empty():
                self._queue.get_nowait()

    async def resume(self, after_s: float = 0.0) -> None:
        self._open_at = self._clock() + after_s
        self._paused = False

    def _gate_open(self) -> bool:
        return not self._paused and self._clock() >= self._open_at

    async def next_utterance(self, timeout_s: float | None) -> Utterance | None:
        q = self._ensure_pump()
        speech: list[bytes] = []
        silence_s = 0.0
        loop = asyncio.get_running_loop()
        deadline = None if timeout_s is None else loop.time() + timeout_s
        while True:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0 and not speech:
                return None
            if self._pump_task is not None and self._pump_task.done() and q.empty():
                return None  # the Ear ended
            try:
                chunk: AudioChunk = await asyncio.wait_for(q.get(), remaining if not speech else None)
            except TimeoutError:
                return None
            if not self._gate_open():
                speech.clear()
                continue
            secs = len(chunk.pcm) / (2 * chunk.sample_rate)
            if rms(chunk.pcm) >= self.threshold:
                speech.append(chunk.pcm)
                silence_s = 0.0
            elif speech:
                speech.append(chunk.pcm)
                silence_s += secs
                if silence_s >= self.pause_s:
                    break
        pcm = b"".join(speech)
        words = await self.recognizer.transcribe(pcm, 16000)
        return Utterance(" ".join(w.text for w in words), words, typed=False, audio_ref=AudioRef(pcm), source="voice")
