"""Prototype P-2: the Xiaomi camera as a microphone through the host go2rtc RTSP stream.

Plan → Prototypes: ffmpeg pulls audio from `rtsp://127.0.0.1:2554/<stream>`; report codec, sample rate,
latency, and whether a child reading at ~1 m is intelligible to Parakeet. Needs the owner (someone must read
aloud near the camera); nothing is played by this script. The capture stays in memory and is transcribed
locally; pass `--keep` to write the 16 kHz wav under cache/ for listening (never commit it).

Owner's command (host go2rtc running, camera online):
    scripts\\win\\go2rtc-host.bat
    .venv\\Scripts\\python scripts/proto/p2_camera_mic.py --seconds 8      (then read a sentence aloud ~1 m away)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leafi.core.config import Settings  # noqa: E402


def probe(url: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "a", "-show_streams",
                          "-of", "json", url], capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout or "{}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:2554")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    settings = Settings()
    url = f"{a.rtsp}/{settings.stream_name}"
    info = probe(url)
    for s in info.get("streams", []):
        print(f"audio stream: codec={s.get('codec_name')} rate={s.get('sample_rate')} channels={s.get('channels')}")
    print(f"pulling {a.seconds}s of audio from {url} → 16 kHz mono int16 (read aloud now)…")
    t0 = time.perf_counter()
    proc = subprocess.run(["ffmpeg", "-v", "error", "-rtsp_transport", "tcp", "-i", url, "-vn", "-t", str(a.seconds),  # noqa: ASYNC221 - owner-run probe
                           "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", "-"],
                          capture_output=True, timeout=a.seconds + 30)
    pcm = proc.stdout
    wall = time.perf_counter() - t0
    import numpy as np

    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    print(f"got {len(x)/16000:.2f}s in {wall:.2f}s wall (startup latency ≈ {wall - len(x)/16000:.2f}s); "
          f"rms {np.sqrt(np.mean(x*x)) if len(x) else 0:.0f}, peak {int(np.abs(x).max()) if len(x) else 0}")
    if proc.stderr:
        print("ffmpeg:", proc.stderr.decode(errors="replace")[-400:])
    if a.keep and pcm:
        from leafi.core.audio import write_wav

        p = Path(settings.cache_dir) / "p2-camera-mic.wav"
        write_wav(p, pcm, 16000)
        print("kept", p)
    from leafi.services import asr

    rec = asr.REGISTRY.create("sherpa", settings)
    t0 = time.perf_counter()
    words = await rec.transcribe(pcm, 16000)
    print(f"Parakeet ({time.perf_counter() - t0:.2f}s):", " ".join(w.text for w in words) or "(nothing)")
    print("word confidences:", [(w.text, w.conf) for w in words])


if __name__ == "__main__":
    asyncio.run(main())
