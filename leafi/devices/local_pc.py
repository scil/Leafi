"""Local PC: Ear via `sounddevice` (16 kHz mono int16), Mouth via `ffplay`, Face on the console.

`sounddevice` is imported only when `listen()` starts (import-time purity, conventions.md).

Capture lifecycle measured by prototype P-6 on the deployment PC (2026-10-20, plan → Surprises):
- `input_device`: `default`, an index, or a case-insensitive name fragment. A fragment usually matches one
  physical device under several host APIs (MME, DirectSound, WASAPI, WDM-KS) and sounddevice refuses the
  ambiguity, so `_resolve_device` picks by host-API preference (WASAPI, then MME, then the rest).
- PortAudio delivers 16 kHz mono int16 from MME and WASAPI devices whose native rate is 44.1/48 kHz (the
  host resamples); `check_input_settings` is asked first and `soxr` resampling is the fallback.
- Overflow arrives as `status.input_overflow` in the callback (none seen at 100 ms blocks, also under a CPU
  burn); it is logged and counted, never raised.
- Unplug does not raise: the callbacks simply stop (a Bluetooth headset also starts ~1 s late). `listen()`
  therefore runs a watchdog: no callback for `lost_after_s` while the stream claims to be active, or the
  stream going inactive, raises `ListenerLost` (TD-16). Replug = the session restarts capture on its next
  attempt; `VoiceListener` surfaces the loss once and the session falls back to the console.
- A Bluetooth headset that drops makes Windows switch the default input, here to "Voicemeeter Out A1", a
  virtual device that delivers digital zeros, so capture "works" and hears nothing (TD-26). The device name is
  logged at open, and `zeros_lost_after_s` (10 s; 0 disables) of all-zero blocks raises `ListenerLost`. A real
  microphone's room floor is never exactly zero (the DJI's is peak 2–5).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import time
from collections.abc import AsyncIterator

from leafi.core.ports import AudioChunk, AudioClip, Display, ListenerLost

log = logging.getLogger("leafi.local_pc")

HOSTAPI_PREFERENCE = ("Windows WASAPI", "MME", "Windows DirectSound", "Core Audio", "ALSA")
RATE = 16000


class LocalPcDevice:
    drain_s = 0.2

    def __init__(self, name: str = "pc", options: dict | None = None, settings=None) -> None:
        opts = options or {}
        self.name = name
        self.input_device = opts.get("input_device", "default")
        self.block_s = float(opts.get("block_s", 0.1))
        self.lost_after_s = float(opts.get("lost_after_s", 3.0))
        self.zeros_lost_after_s = float(opts.get("zeros_lost_after_s", 10.0))
        self.overflows = 0
        self.resolved: int | None = None
        self._proc: asyncio.subprocess.Process | None = None

    # ---- Ear
    def _resolve_device(self, sd) -> int | None:
        """`default` → None (PortAudio default); an int → itself; a name fragment → the best host-API match."""
        dev = self.input_device
        if dev in (None, "", "default"):
            return None
        if isinstance(dev, int) or (isinstance(dev, str) and dev.strip().lstrip("-").isdigit()):
            return int(dev)
        frag = str(dev).lower()
        found = [(i, d) for i, d in enumerate(sd.query_devices())
                 if d["max_input_channels"] > 0 and frag in d["name"].lower()]
        if not found:
            raise ListenerLost(f"no input device matches {dev!r}")

        def rank(item):
            api = sd.query_hostapis(item[1]["hostapi"])["name"]
            return HOSTAPI_PREFERENCE.index(api) if api in HOSTAPI_PREFERENCE else len(HOSTAPI_PREFERENCE)

        return sorted(found, key=rank)[0][0]

    async def listen(self) -> AsyncIterator[AudioChunk]:
        import sounddevice as sd  # lazy: PortAudio

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=200)
        try:
            device = self._resolve_device(sd)
            rate = RATE
            try:
                sd.check_input_settings(device=device, channels=1, dtype="int16", samplerate=RATE)
            except Exception as e:  # noqa: BLE001 - open at the device rate and resample ourselves
                rate = int(sd.query_devices(device, "input")["default_samplerate"])
                log.warning("16 kHz capture refused (%s); capturing at %d Hz and resampling", e, rate)
            resample = _resampler(rate) if rate != RATE else None
            last_cb = [time.monotonic()]

            def callback(indata, frames, time_info, status) -> None:
                last_cb[0] = time.monotonic()
                if status and status.input_overflow:
                    self.overflows += 1
                    log.warning("capture overflow #%d", self.overflows)
                pcm = bytes(indata)
                if resample is not None:
                    pcm = resample(pcm)
                loop.call_soon_threadsafe(_put_drop_oldest, queue, AudioChunk(pcm))

            stream = sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", device=device,
                                       blocksize=int(rate * self.block_s), callback=callback)
        except ListenerLost:
            raise
        except Exception as e:  # noqa: BLE001 - PortAudioError, ValueError (bad device)
            raise ListenerLost(f"capture could not start: {e}") from e
        with stream:
            self.resolved = stream.device
            try:
                dev_name = sd.query_devices(stream.device, "input")["name"]
            except Exception:  # noqa: BLE001 - the name is for the log only
                dev_name = "?"
            log.info("capturing from device %s (%s) at %d Hz", stream.device, dev_name, rate)
            wait = max(1.0, 10 * self.block_s)
            zeros_since: float | None = None
            while True:
                try:
                    chunk = await asyncio.wait_for(queue.get(), wait)
                except TimeoutError:
                    silent_for = time.monotonic() - last_cb[0]
                    if not stream.active:
                        raise ListenerLost("capture stream stopped (device unplugged?)") from None
                    if silent_for >= self.lost_after_s:
                        raise ListenerLost(f"no audio callback for {silent_for:.1f}s (device unplugged?)") from None
                    continue
                if self.zeros_lost_after_s > 0:
                    if chunk.pcm.strip(b"\x00"):
                        zeros_since = None
                    elif zeros_since is None:
                        zeros_since = chunk.t
                    elif chunk.t - zeros_since >= self.zeros_lost_after_s:
                        raise ListenerLost(f"{dev_name!r} delivered only zeros for {chunk.t - zeros_since:.1f}s "
                                           "(headset dropped and the default input changed?)")
                yield chunk

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


def _resampler(rate: int):
    """int16 PCM at `rate` → int16 PCM at 16 kHz (soxr when present, else linear interpolation)."""
    import numpy as np

    try:
        import soxr

        def run(pcm: bytes) -> bytes:
            x = np.frombuffer(pcm, dtype="<i2").astype("float32")
            return soxr.resample(x, rate, RATE).astype("<i2").tobytes()
    except ImportError:
        def run(pcm: bytes) -> bytes:
            x = np.frombuffer(pcm, dtype="<i2").astype("float32")
            idx = np.linspace(0, len(x) - 1, int(len(x) * RATE / rate))
            return np.interp(idx, np.arange(len(x)), x).astype("<i2").tobytes()
    return run


def _put_drop_oldest(queue: asyncio.Queue, item) -> None:
    if queue.full():
        queue.get_nowait()
        log.warning("capture overflow: dropped one chunk")
    queue.put_nowait(item)
