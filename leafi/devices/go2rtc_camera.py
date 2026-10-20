"""go2rtc camera: Eye (`GET /api/frame.jpeg`) and Mouth (`POST /api/streams` speaker push).

Facts ported from `agent/speaker.py` and `agent/tts.py` (keep them true):
- The speaker push is `POST {go2rtc}/api/streams?dst=<stream>&src=ffmpeg:<src_dir>/<file>#audio=<codec>`.
  For the Xiaomi camera, `go2rtc_url` must be the host instance (:2984), which owns the P2P connection;
  `src_dir` must be that instance's view of the file (host = Windows path, container = /cache/tts).
- go2rtc rejects API sources containing spaces (400 "source with spaces may be insecure"), so nothing may
  be passed through `#raw=`: head/tail silence is baked into the file (0.9 s head against the amplifier
  swallowing the first word, 0.6 s tail against truncation when the stream is torn down).
- Codec: Xiaomi = opus (16 kHz mono template in the patched go2rtc), Tapo = pcma.
- A rejected push is logged with the src string and retried once; no retry storm.
Completion: `play()` returns at HTTP accepted + head pad + clip duration; `drain_s` (0.6 s) covers the
tail. `stop()` issues `DELETE /api/streams?src=<pushed src>`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

from leafi.core.audio import pad_wav
from leafi.core.ports import AudioClip, Frame

log = logging.getLogger("leafi.go2rtc")

PAD_HEAD_S = 0.9
PAD_TAIL_S = 0.6


class SourceRejected(ValueError):
    pass


class Go2rtcCamera:
    drain_s = PAD_TAIL_S

    def __init__(self, name: str, options: dict, settings=None, *, transport: httpx.AsyncBaseTransport | None = None,
                 sleep=asyncio.sleep) -> None:
        self.name = name
        self.url = str(options["go2rtc_url"]).rstrip("/")
        self.stream = str(options["stream"])
        self.codec = str(options.get("audio_codec") or "opus")
        self.local_dir = Path(options.get("local_dir") or "cache/tts/camera")
        # src_dir is the go2rtc instance's path to local_dir. Empty → the host instance runs on this machine, so
        # the absolute local_dir (forward slashes) is right. A basename mismatch is the P-5 bug of 2026-10-20
        # (clips written to cache/tts/camera, pushed as cache/tts/…, go2rtc answered 500): warn at once.
        self.src_dir = str(options.get("src_dir") or self.local_dir.resolve().as_posix()).rstrip("/\\")
        if Path(self.src_dir).name != self.local_dir.name:
            log.warning("device %s: src_dir %r does not name the same directory as local_dir %r; "
                        "go2rtc will not find the clips", name, self.src_dir, str(self.local_dir))
        self.snapshot_width = int(options.get("snapshot_width") or 1920)
        self._transport = transport
        self._sleep = sleep
        self._current_src: str | None = None

    def _client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    # ---- Eye
    async def snapshot(self, max_width: int | None = None) -> Frame | None:
        width = max_width or self.snapshot_width
        try:
            async with self._client() as c:
                r = await c.get(f"{self.url}/api/frame.jpeg", params={"src": self.stream, "width": width})
            if r.status_code != 200 or not r.content:
                log.warning("snapshot failed: HTTP %s", r.status_code)
                return None
            return Frame(r.content, r.headers.get("content-type", "image/jpeg"), width)
        except httpx.HTTPError:
            log.warning("snapshot failed: go2rtc unreachable", exc_info=True)
            return None

    # ---- Mouth
    async def prepare(self, clip: AudioClip) -> Path:
        """Write the padded clip into `local_dir` (the directory go2rtc sees as `src_dir`)."""
        self.local_dir.mkdir(parents=True, exist_ok=True)
        if clip.codec == "wav":
            dst = self.local_dir / f"{clip.path.stem}.cam.wav"
            if not dst.exists():
                pad_wav(clip.path, dst, PAD_HEAD_S, PAD_TAIL_S)
            return dst
        dst = self.local_dir / f"{clip.path.stem}.cam{clip.path.suffix}"
        if dst.exists():
            return dst
        if shutil.which("ffmpeg"):
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-loglevel", "quiet", "-i", str(clip.path),
                "-af", f"adelay={int(PAD_HEAD_S * 1000)}:all=1,apad=pad_dur={PAD_TAIL_S}", str(dst))
            await proc.wait()
            if proc.returncode == 0 and dst.exists():
                return dst
        log.warning("ffmpeg unavailable; pushing %s without silence padding", clip.path.name)
        shutil.copyfile(clip.path, dst)
        return dst

    def source_for(self, file: Path) -> str:
        src = f"ffmpeg:{self.src_dir}/{file.name}#audio={self.codec}"
        if " " in src:
            raise SourceRejected(f"go2rtc rejects sources with spaces: {src!r} (fix SPEAKER_SRC_DIR)")
        return src

    async def play(self, clip: AudioClip) -> None:
        file = await self.prepare(clip)
        try:
            src = self.source_for(file)
        except SourceRejected:
            log.error("speaker push refused before sending", exc_info=True)
            return
        accepted = False
        for attempt in (1, 2):  # one retry, no storm
            try:
                async with self._client() as c:
                    r = await c.post(f"{self.url}/api/streams", params={"dst": self.stream, "src": src})
                    r.raise_for_status()
                accepted = True
                break
            except httpx.HTTPError as e:
                log.error("speaker push failed (attempt %d) src=%s: %s", attempt, src, e)
        if not accepted:
            return
        self._current_src = src
        try:
            await self._sleep(PAD_HEAD_S + clip.duration_s)
        finally:
            self._current_src = None

    async def stop(self) -> None:
        src = self._current_src
        if not src:
            return
        try:
            async with self._client(5.0) as c:
                await c.delete(f"{self.url}/api/streams", params={"src": src})
        except httpx.HTTPError:
            log.warning("speaker stop failed src=%s", src, exc_info=True)
