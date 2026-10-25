"""One console check per independently verifiable step of a study session, each on the code path a session uses.

    .venv\\Scripts\\python scripts/probes/checks.py snapshot   # the study Eye's frame (go2rtc), saved and opened
    .venv\\Scripts\\python scripts/probes/checks.py ocr [FILE] # a fresh frame (or FILE) through the page OCR
    .venv\\Scripts\\python scripts/probes/checks.py ocr-last   # the latest snapshot again, without a new capture
    .venv\\Scripts\\python scripts/probes/checks.py mic        # 3 s from the study Ear as the session opens it
    .venv\\Scripts\\python scripts/probes/checks.py tts        # one English and one Chinese line, written, not played
    .venv\\Scripts\\python scripts/probes/checks.py speaker    # plays tts's two clips on the PC speaker (makes sound)

Only `speaker` makes sound, and only on the PC Mouth, never the camera. Files go to `cache/checks/` (gitignored).
`mic` keeps the audio in memory only. `tts`'s Chinese line goes to Microsoft through egress, attributed to an
invented learner on a throwaway database, so `data/leafi.db` is never opened by any check.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leafi import bootstrap  # noqa: E402
from leafi.core.config import Settings  # noqa: E402

TTS_LINES = (("en", "Great reading! Let's try fox together."), ("zh", "你好，我们开始读书吧。"))


def _out(settings: Settings) -> Path:
    out = settings.cache_dir / "checks"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _built(settings: Settings):
    from leafi import app

    return app.build(settings, voice_policy="none")


async def snapshot(settings: Settings, *, show: bool = True) -> Path | None:
    eye = _built(settings).hub.eye()
    if eye is None:
        print("FAIL no study Eye in config/devices.yml")
        return None
    t = time.monotonic()
    frame = await eye.snapshot()
    if frame is None:
        print("FAIL no frame: is the host go2rtc running and the camera online? (console: 重启 go2rtc)")
        return None
    path = _out(settings) / "snapshot.jpg"
    path.write_bytes(frame.data)
    print(f"ok   {len(frame.data)} bytes in {time.monotonic() - t:.1f}s -> {path}")
    if show and hasattr(os, "startfile"):
        os.startfile(path)  # noqa: S606 - opens the saved still in the default image viewer
    return path


def _ocr_parameters(settings: Settings, backend) -> None:
    """The evaluation window: the parameters the page OCR runs with (design 2026-10-25 O8)."""
    from leafi.services.ocr import rapidocr

    if not isinstance(backend, rapidocr.RapidOcr):
        print(f"     backend {settings.ocr_backend}: no per-angle scores")
        return
    print(f"     params: {backend.version}, OCR_ROTATIONS {','.join(map(str, backend.rotations))}, probe "
          f"{rapidocr.PROBE_K} lines, line classifier off, a pass is a page with >= {rapidocr.MIN_BODY} wide "
          f"confident lines (conf >= 0.85, > 3 chars) scoring >= {rapidocr.MIN_SCORE:.0f}, sure when the "
          f"runner-up <= {rapidocr.MARGIN} x best")


def report_ocr(res, seconds: float, path) -> int:
    """Print what the backend did and chose; run no engine here, so the console shows the session's own choice."""
    import statistics

    if res.probe is not None:
        nominee, scores, secs = res.probe
        shown = ", ".join(f"{a}°: {s:.0f}" for a, s in scores.items()) or "no line-like boxes"
        print(f"     probe: {shown} -> {f'{nominee}°' if nominee is not None else 'none'} ({secs:.2f}s)")
    for p in res.passes:
        print(f"     pass {p.angle:>3}° {p.kind:<10} score {p.score:6.1f}, wide {p.wide}/{p.total}, {p.seconds:.2f}s")
    body = [ln for ln in res.lines if ln.body]
    height = f", body line height {statistics.median(ln.height for ln in body):.0f} px" if body else ""
    ok = res.state == "sure" and len(body) >= 3
    verdict = "ok  " if ok else "WEAK"
    print(f"{verdict} {res.state}, rotation {res.rotation}°, {len(res.lines)} lines, {len(body)} body lines"
          f"{height}, {seconds:.1f}s ({path})")
    for ln in res.lines:
        print(f"  {ln.conf:.2f}  {ln.text}")
    if not ok:
        print("     not sure: lay the book flat, hands off, page filling a third of the frame; text under ~15 px "
              "tall reads poorly")
    return 0 if ok else 1


async def ocr(settings: Settings, file: Path | None) -> int:
    from leafi.core.ports import Frame
    from leafi.services import ocr as ocr_service

    path = file or await snapshot(settings, show=False)
    if path is None:
        return 1
    state, detail = ocr_service.REGISTRY.status(settings.ocr_backend, settings)
    if state != "ok":
        print(f"FAIL ocr {settings.ocr_backend}: {state} {detail}")
        return 1
    backend = ocr_service.REGISTRY.create(settings.ocr_backend, settings)
    _ocr_parameters(settings, backend)
    t = time.monotonic()
    try:
        res = await backend.read(Frame(Path(path).read_bytes()), purpose="page")
    finally:
        if hasattr(backend, "aclose"):
            await backend.aclose()
    return report_ocr(res, time.monotonic() - t, path)


async def mic(settings: Settings, seconds: float = 3.0) -> int:
    built = _built(settings)
    ear_name = built.config.study_listener
    ear = built.devices.get(ear_name)
    ear = ear if hasattr(ear, "listen") else None
    if ear is None:
        print(f"FAIL study listener {ear_name!r} is not an Ear on this PC")
        return 1
    print(f"     speak now: {seconds:.0f} s from {ear_name!r} (input_device {getattr(ear, 'input_device', '?')!r})")
    samples, peak, total_sq = 0, 0, 0.0
    t0 = time.monotonic()
    try:
        async for chunk in ear.listen():
            vals = struct.unpack(f"<{len(chunk.pcm) // 2}h", chunk.pcm)
            samples += len(vals)
            peak = max(peak, max((abs(v) for v in vals), default=0))
            total_sq += sum(v * v for v in vals)
            if time.monotonic() - t0 >= seconds:
                break
    except Exception as e:  # noqa: BLE001 - reported for the owner, with the type
        print(f"FAIL {type(e).__name__}: {e}")
        return 1
    finally:
        if hasattr(ear, "stop"):
            await ear.stop()
    rms = math.sqrt(total_sq / samples) if samples else 0.0
    device = getattr(ear, "resolved", None)
    heard = samples / 16000
    ok = peak >= 300
    print(f"{'ok  ' if ok else 'FAIL'} device {device}: {heard:.1f}s captured, rms {rms:.0f}, peak {peak}"
          + ("" if ok else " — silence: is the DJI headset connected over Bluetooth and switched on?"))
    return 0 if ok else 1


async def tts(settings: Settings) -> int:
    from leafi.core import learner_store
    from leafi.core.storage import Store
    from leafi.privacy import runtime
    from leafi.services.tts import create as tts_create

    out = _out(settings)
    failed = 0
    with tempfile.TemporaryDirectory(prefix="leafi-check-") as tmp:
        scratch = settings.model_copy(update={"data_dir": Path(tmp)})
        egress = runtime.get(scratch)
        with Store(scratch.db_path) as store:
            learner = learner_store.create(store, "Check")
        egress.start_detector()
        await asyncio.to_thread(egress._det_done.wait, 120)
        service = tts_create(scratch)
        with runtime.attributed(learner):
            for lang, text in TTS_LINES:
                be = service._backend(lang)
                t = time.monotonic()
                try:
                    clip = await be.synthesize(text, lang, False, out / f"tts-{lang}")
                    print(f"ok   {lang} {getattr(be, 'name', '?')}: {clip.duration_s:.1f}s of audio in "
                          f"{time.monotonic() - t:.1f}s -> {clip.path}")
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"FAIL {lang} {getattr(be, 'name', '?')}: {type(e).__name__} {str(e)[:160]}")
        egress.close()
    return 1 if failed else 0


async def speaker(settings: Settings) -> int:
    """Plays `tts`'s two clips on the PC Mouth (never the camera): the one check that makes sound."""
    from leafi.core.ports import AudioClip

    pc = _built(settings).devices.get("pc")
    clips = [p for p in (_out(settings) / "tts-en.wav", _out(settings) / "tts-zh.mp3") if p.exists()]
    if pc is None or not hasattr(pc, "play"):
        print("FAIL no `pc` Mouth in config/devices.yml")
        return 1
    if not clips:
        print("FAIL no clips yet: run the TTS check first")
        return 1
    import shutil

    if not shutil.which("ffplay"):  # the PC Mouth plays through ffplay and only logs when it is missing
        print("FAIL ffplay not found: install ffmpeg")
        return 1
    for path in clips:
        codec = path.suffix.lstrip(".")
        await pc.play(AudioClip(path, 0.0, 24000, 1, codec))
        print(f"ok   played {path.name} on the PC speaker")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("check", choices=("snapshot", "ocr", "ocr-last", "mic", "tts", "speaker"))
    p.add_argument("file", nargs="?", type=Path, help="ocr: an image to read instead of a fresh snapshot")
    args = p.parse_args()
    settings = Settings()
    bootstrap.install(settings)
    if args.check == "snapshot":
        return 0 if asyncio.run(snapshot(settings)) else 1
    if args.check == "ocr":
        return asyncio.run(ocr(settings, args.file))
    if args.check == "ocr-last":
        last = _out(settings) / "snapshot.jpg"
        if not last.exists():
            print("FAIL no snapshot yet: click 摄像头截图 or OCR(新拍) first")
            return 1
        print(f"     latest snapshot, taken {time.strftime('%H:%M:%S', time.localtime(last.stat().st_mtime))}")
        return asyncio.run(ocr(settings, last))
    if args.check == "mic":
        return asyncio.run(mic(settings))
    if args.check == "speaker":
        return asyncio.run(speaker(settings))
    return asyncio.run(tts(settings))


if __name__ == "__main__":
    sys.exit(main())
