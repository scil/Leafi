"""Local PC: Ear via `sounddevice` (16 kHz mono int16), Mouth via `ffplay`, Face on the console.

S3 shell: `sounddevice` is imported only when `listen()` starts (import-time purity, conventions.md).
The capture lifecycle (device selection, overflow, unplug, pause under load) is prototype P-6.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from collections.abc import AsyncIterator

from leafi.core.ports import AudioChunk, AudioClip, Display

log = logging.getLogger("leafi.local_pc")


class LocalPcDevice:
    drain_s = 0.2

    def __init__(self, name: str = "pc", options: dict | None = None, settings=None) -> None:
        opts = options or {}
        self.name = name
        device = opts.get("input_device", "default")
        self.input_device = None if device in (None, "default") else device
        self.block_s = float(opts.get("block_s", 0.1))
        self._proc: asyncio.subprocess.Process | None = None

    # ---- Ear
    async def listen(self) -> AsyncIterator[AudioChunk]:
        import sounddevice as sd  # lazy: PortAudio

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=200)

        def callback(indata, frames, time_info, status) -> None:
            if status:
                log.warning("capture status: %s", status)
            chunk = AudioChunk(bytes(indata))
            loop.call_soon_threadsafe(_put_drop_oldest, queue, chunk)

        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", device=self.input_device,
                               blocksize=int(16000 * self.block_s), callback=callback):
            while True:
                yield await queue.get()

    # ---- Mouth
    async def play(self, clip: AudioClip) -> None:
        if not shutil.which("ffplay"):
            log.error("ffplay not found; install ffmpeg")
            return
        self._proc = await asyncio.create_subprocess_exec(
            "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(clip.path))
        try:
            await self._proc.wait()
        finally:
            self._proc = None

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()

    # ---- Face
    async def show(self, msg: Display) -> None:
        sys.stdout.write(f"[{self.name}] {msg.text}\n")


def _put_drop_oldest(queue: asyncio.Queue, item) -> None:
    if queue.full():
        queue.get_nowait()
        log.warning("capture overflow: dropped one chunk")
    queue.put_nowait(item)
