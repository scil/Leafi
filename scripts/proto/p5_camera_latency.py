"""Prototype P-5: Kokoro → prepared clip → camera speaker: end-to-audible latency and truncation.

AUDIBLE IN THE CHILD'S HOME. Run only when the owner says so, with the owner next to the camera
(AGENTS.md: never play audio on the camera speaker unasked). Measures what performance.md budgets at
≤ 2.5 s end-to-audible on the camera (0.9 s head pad is fixed cost) and whether a word and a line are
truncated at the start or the end.

Two ways to time it (host go2rtc running, camera online):
    .venv\\Scripts\\python scripts/proto/p5_camera_latency.py --i-am-present --auto
        The camera microphone records its own speaker through rtsp://127.0.0.1:2554/<stream> (P-2 showed it
        hears the room): the script pushes each clip, finds the audible onset and offset in the recording, and
        prints end-to-audible latency (±0.3 s: the RTSP pull starts ~0.8 s late and that offset is estimated
        from the pull's own wall clock) and the heard duration against the clip duration (truncation).
    .venv\\Scripts\\python scripts/proto/p5_camera_latency.py --i-am-present
        Manual: press Enter to push, Enter again when you hear it, then answer the truncation question. Needs a
        real interactive console (the app's Terminal panel handed `input()` an EOF on 2026-10-20).
Without `--i-am-present` it only prepares the clips and prints the push command it would send.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leafi.core.config import Settings  # noqa: E402

LINES = ["through", "Let's try that word once more.", "The little brown dog walked slowly down the hill."]
RATE = 16000


def start_pull(url: str, seconds: float) -> tuple[subprocess.Popen, float]:
    proc = subprocess.Popen(  # noqa: ASYNC220 - owner-run probe; the pull must overlap the push
        ["ffmpeg", "-v", "error", "-rtsp_transport", "tcp", "-i", url, "-vn", "-t", str(seconds),
         "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(RATE), "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc, time.perf_counter()


def onset_offset(pcm: bytes, floor_s: float = 1.0) -> tuple[float | None, float | None, float, float]:
    """First and last 20 ms window above 8× the noise floor (floor = rms of the first `floor_s`)."""
    import numpy as np

    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    win = RATE // 50
    n = len(x) // win
    if n < 10:
        return None, None, 0.0, 0.0
    frames = x[: n * win].reshape(n, win)
    rms = np.sqrt((frames * frames).mean(axis=1))
    floor = max(2.0, float(rms[: int(floor_s * 50)].mean()))
    loud = np.where(rms > 8 * floor)[0]
    if not len(loud):
        return None, None, floor, float(rms.max())
    return loud[0] * win / RATE, (loud[-1] + 1) * win / RATE, floor, float(rms.max())


async def auto(cam, service, stream: str, rtsp: str) -> None:
    url = f"{rtsp}/{stream}"
    print("| line | synth s | clip s | push→accepted s | end-to-audible s (±0.3) | heard s | note |")
    print("|---|---|---|---|---|---|---|")
    for text in LINES:
        t0 = time.perf_counter()
        clip = await service.synth(text, "en")
        t_synth = time.perf_counter() - t0
        prepared = await cam.prepare(clip)
        cam.source_for(prepared)
        total = 3.0 + 0.9 + clip.duration_s + 3.0
        proc, t_pull = start_pull(url, total)
        reader = asyncio.get_running_loop().run_in_executor(None, proc.stdout.read)
        await asyncio.sleep(3.0)  # noise floor first
        t_push = time.perf_counter()
        play = asyncio.create_task(cam.play(clip))
        # cam.play returns at HTTP accepted + head pad + duration; the accepted moment is when _current_src is set
        accepted = None
        while not play.done():
            await asyncio.sleep(0.01)
            if accepted is None and cam._current_src is not None:
                accepted = time.perf_counter() - t_push
        await play
        pcm = await reader
        proc.wait(timeout=10)
        on, off, floor, peak = onset_offset(pcm)
        # the first delivered sample corresponds to roughly t_pull + startup latency; estimate the startup
        # latency from how much audio arrived versus the wall time of the pull
        got_s = len(pcm) / (2 * RATE)
        startup = max(0.0, (time.perf_counter() - t_pull) - got_s)
        if on is None:
            print(f"| {text} | {t_synth:.2f} | {clip.duration_s:.2f} | {accepted if accepted is None else round(accepted, 2)} | "
                  f"not heard | - | floor rms {floor:.0f}, peak {peak:.0f}; push accepted={accepted is not None} |")
            continue
        audible = (on + startup) - (t_push - t_pull)
        heard = off - on
        note = "ok"
        if heard < clip.duration_s - 0.25:
            note = f"TRUNCATED by {clip.duration_s - heard:.2f}s"
        elif heard > clip.duration_s + 0.6:
            note = "longer than the clip (room echo or a second sound)"
        print(f"| {text} | {t_synth:.2f} | {clip.duration_s:.2f} | {accepted:.2f} | {audible:.2f} | {heard:.2f} | "
              f"{note}; floor {floor:.0f} peak {peak:.0f} |")
        await asyncio.sleep(2.0)


async def manual(cam, service) -> None:
    for text in LINES:
        t0 = time.perf_counter()
        clip = await service.synth(text, "en")
        t_synth = time.perf_counter() - t0
        prepared = await cam.prepare(clip)
        src = cam.source_for(prepared)
        print(f"\n'{text}': synth {t_synth:.2f}s, clip {clip.duration_s:.2f}s, src={src}")
        try:
            input("  Press Enter to push, then press Enter again the moment you hear it start… ")  # noqa: ASYNC250
        except EOFError:
            print("  no interactive stdin here (EOF); run from a real console or use --auto")
            return
        t_push = time.perf_counter()
        task = asyncio.create_task(cam.play(clip))
        await asyncio.get_running_loop().run_in_executor(None, input, "")
        heard = time.perf_counter() - t_push
        await task
        cut = input("  Was the first word cut? the last word? (none / first / last / both): ").strip()  # noqa: ASYNC250
        print(f"  end-to-audible {heard:.2f}s (budget 2.5 s incl. 0.9 s head pad); truncation: {cut or 'none'}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--i-am-present", action="store_true", help="the owner is at the camera and wants sound")
    ap.add_argument("--auto", action="store_true", help="time the speaker through the camera microphone")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:2554")
    ap.add_argument("--only", type=int, help="play only this line (1-based); the owner wants the text first")
    a = ap.parse_args()
    if a.only:
        LINES[:] = [LINES[a.only - 1]]
    from leafi import app as composition
    from leafi.services import tts

    settings = Settings()
    built = composition.build(settings, text_mode=False, voice_policy="primary")
    cam = built.devices.get("desk_cam")
    if cam is None:
        print("desk_cam is disabled (missing .env values?):", built.warnings)
        return
    service = tts.create(settings)
    if not a.i_am_present:
        for text in LINES:
            clip = await service.synth(text, "en")
            src = cam.source_for(await cam.prepare(clip))
            print(f"(dry run) '{text}' clip {clip.duration_s:.2f}s would POST {cam.url}/api/streams?dst={cam.stream}&src={src}")
        return
    if a.auto:
        await auto(cam, service, settings.stream_name, a.rtsp)
    else:
        await manual(cam, service)


if __name__ == "__main__":
    asyncio.run(main())
