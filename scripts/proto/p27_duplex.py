"""Prototype for TD-27: does the camera microphone keep hearing a voice while the camera speaker plays?

AUDIBLE IN THE CHILD'S HOME unless `--clip silence`. Run only when the owner says they are present.
go2rtc v1.9.14's xiaomi/miss producer forwards every microphone packet unconditionally and opens talk with a
bare `cmdSpeakerStartReq` (never `cmdSpeakerStop`), so a silent microphone during talk is the camera's doing:
either a hold-to-talk mute on speaker start, or echo cancellation that also takes the near voice.

One run pulls the camera microphone (RTSP) and the PC microphone (reference) for `--seconds`, pushes one clip
at `--push-at` seconds, prints rms per second for both, and transcribes the camera track before, during and
after playback. Owner protocol: count aloud slowly ("one … twenty", about one word a second) from the start,
about 1 m from the camera.

    .venv\\Scripts\\python scripts/proto/p27_duplex.py --i-am-present --mic DJI --clip silence
        speaker channel opens but plays silence: microphone lost → hold-to-talk mute, not echo cancellation
    .venv\\Scripts\\python scripts/proto/p27_duplex.py --i-am-present --mic DJI --clip 2
        plays "Let's try that word once more." (announce it first)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p5_camera_latency as p5  # noqa: E402

from leafi.core.config import Settings  # noqa: E402

RATE = p5.RATE


def per_second(pcm: bytes) -> list[int]:
    import numpy as np

    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    n = len(x) // RATE
    return [int(np.sqrt((x[i * RATE:(i + 1) * RATE] ** 2).mean())) for i in range(n)]


def per_step(pcm: bytes, start_s: float, end_s: float, step_s: float = 0.1) -> list[tuple[float, int]]:
    import numpy as np

    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    out, t = [], max(0.0, start_s)
    while t + step_s <= min(end_s, len(x) / RATE):
        seg = x[int(t * RATE):int((t + step_s) * RATE)]
        out.append((t, int(np.sqrt((seg ** 2).mean()))))
        t += step_s
    return out


def cut(pcm: bytes, start_s: float, end_s: float) -> bytes:
    a, b = max(0, int(start_s * RATE)) * 2, max(0, int(end_s * RATE)) * 2
    return pcm[a:b]


async def silence_clip(seconds: float):
    from leafi.core.audio import silence, write_wav
    from leafi.core.ports import AudioClip

    path = Path("cache") / "tts" / f"p27-silence-{int(seconds * 1000)}.wav"
    write_wav(path, silence(seconds, 24000), 24000)
    return AudioClip(path, seconds)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--i-am-present", action="store_true", help="the owner is at the camera and wants this run")
    ap.add_argument("--clip", default="silence", help="'silence' or a 1-based index into p5's LINES")
    ap.add_argument("--silence-s", type=float, default=1.7, help="length of the silent clip (line 2 is ~1.7 s)")
    ap.add_argument("--seconds", type=float, default=18.0)
    ap.add_argument("--push-at", type=float, default=5.0)
    ap.add_argument("--mic", default="DJI", help="PC reference microphone (sounddevice name); 'none' to skip")
    ap.add_argument("--rtsp", default="rtsp://127.0.0.1:2554")
    ap.add_argument("--keep", action="store_true", help="write both tracks as wav under cache/")
    ap.add_argument("--fine", action="store_true",
                    help="rms per 100 ms around the end of playback (recovery edge; owner keeps a steady voice)")
    a = ap.parse_args()

    from leafi import app as composition
    from leafi.services import asr, tts

    settings = Settings()
    built = composition.build(settings, text_mode=False, voice_policy="primary")
    cam = built.devices.get("desk_cam")
    if cam is None:
        print("desk_cam is disabled (missing .env values?):", built.warnings)
        return
    if a.clip == "silence":
        clip, label = await silence_clip(a.silence_s), f"silence {a.silence_s:.1f}s"
    else:
        text = p5.LINES[int(a.clip) - 1]
        clip, label = await tts.create(settings).synth(text, "en"), repr(text)
    cam.source_for(await cam.prepare(clip))
    if not a.i_am_present:
        print(f"(dry run) would pull {a.rtsp}/{settings.stream_name} for {a.seconds}s and push {label} at {a.push_at}s")
        return

    mic_ctx = None
    if a.mic != "none":
        import sounddevice as sd

        from leafi.devices.local_pc import LocalPcDevice

        mic_ctx = p5.MicRecorder(LocalPcDevice("pc", {"input_device": a.mic})._resolve_device(sd))
        mic_ctx.__enter__()
    try:
        proc, t_pull = p5.start_pull(f"{a.rtsp}/{settings.stream_name}", a.seconds)
        reader = asyncio.get_running_loop().run_in_executor(None, proc.stdout.read)
        print(f"recording {a.seconds:.0f}s — start counting now; push {label} at {a.push_at:.0f}s")
        await asyncio.sleep(a.push_at)
        t_push = time.perf_counter()
        play = asyncio.create_task(cam.play(clip))
        t_acc = None
        while not play.done():
            await asyncio.sleep(0.01)
            if t_acc is None and cam._current_src is not None:
                t_acc = time.perf_counter()
        await play
        t_end = time.perf_counter()
        pcm = await reader
        proc.wait(timeout=10)
    finally:
        if mic_ctx is not None:
            mic_ctx.__exit__(None, None, None)

    got = len(pcm) / (2 * RATE)
    startup = max(0.0, (time.perf_counter() - t_pull) - got)  # first camera sample ≈ t_pull + startup

    def cam_off(t: float) -> float:
        return t - t_pull - startup

    if t_acc is None:
        print("push NOT accepted (go2rtc down or TD-25?); nothing played")
        return
    play_on = cam_off(t_acc + 0.9)  # head pad, then the clip
    play_off = cam_off(t_end + cam.drain_s)
    print(f"camera track {got:.1f}s (startup ≈ {startup:.2f}s); push→accepted {t_acc - t_push:.2f}s; "
          f"playback window in the camera track ≈ {play_on:.1f}–{play_off:.1f}s (±0.3)")
    cam_rms = per_second(pcm)
    print("camera mic rms/s:", " ".join(f"{i}:{v}" for i, v in enumerate(cam_rms)))
    pc_pcm = b""
    if mic_ctx is not None and mic_ctx.stamps:
        pc_pcm = b"".join(mic_ctx.chunks)
        # align the PC track to the camera track's time axis
        pc_first = mic_ctx.stamps[0] - mic_ctx.block / RATE
        shift = (t_pull + startup) - pc_first
        pc_pcm = cut(pc_pcm, shift, shift + got) if shift >= 0 else b"\x00\x00" * int(-shift * RATE) + pc_pcm
        print("PC mic rms/s:    ", " ".join(f"{i}:{v}" for i, v in enumerate(per_second(pc_pcm))))
    if a.fine:
        pc_steps = dict(per_step(pc_pcm, play_off - 1.0, play_off + 2.5)) if pc_pcm else {}
        print("t-play_off  camera  pc")
        for t, v in per_step(pcm, play_off - 1.0, play_off + 2.5):
            print(f"{t - play_off:+5.1f}s  {v:6d}  {pc_steps.get(t, '')}")

    rec = asr.REGISTRY.create("sherpa", settings)
    windows = [("before", 0.0, play_on), ("during", play_on, play_off), ("after", play_off, got)]
    for name, s, e in windows:
        words = await rec.transcribe(cut(pcm, s, e), RATE)
        print(f"camera {name:6} {s:5.1f}–{e:5.1f}s: " + (" ".join(f"{w.text}({w.conf:.2f})" for w in words) or "(nothing)"))
    if pc_pcm:
        for name, s, e in windows:
            words = await rec.transcribe(cut(pc_pcm, s, e), RATE)
            print(f"pc     {name:6} {s:5.1f}–{e:5.1f}s: " + (" ".join(w.text for w in words) or "(nothing)"))
    if a.keep:
        from leafi.core.audio import write_wav

        stem = "silence" if a.clip == "silence" else f"line{a.clip}"
        write_wav(Path("cache") / f"p27-cam-{stem}.wav", pcm, RATE)
        if pc_pcm:
            write_wav(Path("cache") / f"p27-pc-{stem}.wav", pc_pcm, RATE)
        print("kept cache/p27-*.wav")


if __name__ == "__main__":
    asyncio.run(main())
