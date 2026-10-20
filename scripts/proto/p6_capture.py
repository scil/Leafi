"""Prototype P-6: `sounddevice` capture lifecycle on this PC.

Questions (plan → Prototypes): device selection (name / index / default), whether PortAudio delivers 16 kHz
mono int16 from the default device or resampling is ours, overflow signalling, unplug/replug, and capture
under model load. Captures a few seconds into memory, prints numbers, writes nothing, plays nothing.

Run:  .venv\\Scripts\\python scripts/proto/p6_capture.py [--device NAME_OR_INDEX] [--seconds 3] [--load]
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

import numpy as np
import sounddevice as sd


def pick(device: str | None):
    if device in (None, "", "default"):
        return None
    try:
        return int(device)
    except ValueError:
        return device  # sounddevice matches a case-insensitive substring of the name


def capture(device, seconds: float, samplerate: int, block_s: float, load: bool) -> None:
    q: queue.Queue = queue.Queue()
    statuses: list[str] = []
    gaps: list[float] = []
    last = [time.perf_counter()]

    def cb(indata, frames, t, status):
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
        if status:
            statuses.append(str(status))
        q.put(bytes(indata))

    stop = threading.Event()
    if load:  # a model-sized CPU burn in the background, like OCR/ASR running during capture
        def burn():
            a = np.random.default_rng(0).random((800, 800))
            while not stop.is_set():
                a = a @ a / 800
        threading.Thread(target=burn, daemon=True).start()
    try:
        with sd.RawInputStream(samplerate=samplerate, channels=1, dtype="int16", device=device,
                               blocksize=int(samplerate * block_s), callback=cb) as st:
            info = sd.query_devices(st.device)
            print(f"opened device {st.device}: {info['name']!r} hostapi={sd.query_hostapis(info['hostapi'])['name']} "
                  f"default_sr={info['default_samplerate']} stream_sr={st.samplerate} latency={st.latency:.3f}s "
                  f"blocksize={st.blocksize}")
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < seconds:
                time.sleep(0.05)
                if not st.active:
                    print("stream became inactive (device gone?)")
                    break
    finally:
        stop.set()
    chunks = []
    while not q.empty():
        chunks.append(q.get())
    pcm = b"".join(chunks)
    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    got = len(x) / samplerate
    print(f"captured {got:.2f}s of {seconds}s; chunks={len(chunks)} rms={rms:.1f} peak={int(np.abs(x).max()) if len(x) else 0} "
          f"statuses={sorted(set(statuses))} callback gap p50={np.median(gaps[1:]) * 1000:.0f}ms "
          f"max={max(gaps[1:]) * 1000:.0f}ms")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--rate", type=int, default=16000)
    ap.add_argument("--block", type=float, default=0.1)
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    print(f"sounddevice {sd.__version__}, PortAudio {sd.get_portaudio_version()[1]}")
    print("default devices (in, out):", sd.default.device)
    if a.list:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"  {i:3d} in={d['max_input_channels']} sr={d['default_samplerate']} "
                      f"{sd.query_hostapis(d['hostapi'])['name']}: {d['name']}")
        return
    dev = pick(a.device)
    try:
        sd.check_input_settings(device=dev, channels=1, dtype="int16", samplerate=a.rate)
        print(f"check_input_settings({a.rate} Hz mono int16) ok")
    except Exception as e:  # noqa: BLE001
        print(f"check_input_settings failed: {e}")
    capture(dev, a.seconds, a.rate, a.block, a.load)


if __name__ == "__main__":
    sys.exit(main())
