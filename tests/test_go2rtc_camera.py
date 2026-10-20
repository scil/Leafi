"""go2rtc Eye + Mouth against a fake go2rtc HTTP server on loopback. No camera is ever contacted."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from leafi.core.audio import read_wav, silence, write_wav
from leafi.core.ports import AudioClip
from leafi.devices.go2rtc_camera import PAD_HEAD_S, PAD_TAIL_S, Go2rtcCamera

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class FakeGo2rtc:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.fail_posts = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _record(self):
                u = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                outer.requests.append((self.command, u.path, q))
                return u.path, q

            def do_GET(self):
                path, q = self._record()
                if path == "/api/frame.jpeg":
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.end_headers()
                    self.wfile.write(JPEG)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                path, q = self._record()
                if outer.fail_posts:
                    outer.fail_posts -= 1
                    self.send_response(500)
                elif " " in q.get("src", ""):
                    self.send_response(400)  # "source with spaces may be insecure"
                else:
                    self.send_response(200)
                self.end_headers()

            def do_DELETE(self):
                self._record()
                self.send_response(200)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def go2rtc():
    srv = FakeGo2rtc()
    yield srv
    srv.close()


def _cam(go2rtc, tmp_path, **opts):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    options = {"go2rtc_url": go2rtc.url, "stream": "cam_xiaomi", "audio_codec": "opus",
               "src_dir": "E:/GitHub/scil/Leafi/cache/tts/camera", "local_dir": str(tmp_path / "camera"), **opts}
    return Go2rtcCamera("desk_cam", options, sleep=fake_sleep), sleeps


def _clip(tmp_path, seconds=1.0) -> AudioClip:
    p = tmp_path / "abc123.wav"
    dur = write_wav(p, silence(seconds), 16000)
    return AudioClip(p, dur, 16000, 1, "wav")


async def test_snapshot_gets_a_frame_with_src_and_width(go2rtc, tmp_path):
    cam, _ = _cam(go2rtc, tmp_path)
    frame = await cam.snapshot(1920)
    assert frame.data == JPEG and frame.width == 1920
    assert go2rtc.requests == [("GET", "/api/frame.jpeg", {"src": "cam_xiaomi", "width": "1920"})]


async def test_snapshot_failure_returns_none(tmp_path):
    cam = Go2rtcCamera("c", {"go2rtc_url": "http://127.0.0.1:9", "stream": "s", "src_dir": "x"})
    assert await cam.snapshot() is None


def test_shipped_devices_yml_maps_src_dir_onto_local_dir():
    """P-5 (2026-10-20): clips were written to cache/tts/camera and pushed as cache/tts/…, go2rtc answered 500.
    With the habit track's SPEAKER_SRC_DIR (…/cache/tts) both paths must end in the same directory name."""
    from pathlib import Path

    from leafi.core.hub import load_devices_config

    env = {"GO2RTC_URL": "http://127.0.0.1:2984", "STREAM_NAME": "cam_xiaomi",
           "SPEAKER_SRC_DIR": "E:/GitHub/scil/Leafi/cache/tts"}
    cfg = load_devices_config(Path("config/devices.yml"), env.get)
    cam = next(d for d in cfg.devices if d.adapter == "go2rtc_camera")
    assert Path(cam.options["src_dir"]).name == Path(cam.options["local_dir"]).name == "camera"


def test_src_dir_mismatch_is_warned_and_empty_src_dir_falls_back_to_local_dir(tmp_path, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="leafi.go2rtc"):
        Go2rtcCamera("c", {"go2rtc_url": "http://127.0.0.1:9", "stream": "s", "src_dir": "E:/x/cache/tts",
                           "local_dir": str(tmp_path / "camera")})
    assert any("does not name the same directory" in r.message for r in caplog.records)
    cam = Go2rtcCamera("c", {"go2rtc_url": "http://127.0.0.1:9", "stream": "s", "local_dir": str(tmp_path / "camera")})
    assert cam.src_dir == (tmp_path / "camera").resolve().as_posix()


async def test_play_pads_the_clip_and_pushes_a_space_free_source(go2rtc, tmp_path):
    cam, sleeps = _cam(go2rtc, tmp_path)
    clip = _clip(tmp_path, 1.0)
    await cam.play(clip)
    (method, path, q), = go2rtc.requests
    assert (method, path) == ("POST", "/api/streams")
    assert q == {"dst": "cam_xiaomi", "src": "ffmpeg:E:/GitHub/scil/Leafi/cache/tts/camera/abc123.cam.wav#audio=opus"}
    padded = tmp_path / "camera" / "abc123.cam.wav"
    pcm, sr, _ = read_wav(padded)
    assert len(pcm) / (2 * sr) == pytest.approx(PAD_HEAD_S + 1.0 + PAD_TAIL_S, abs=0.01)
    assert sleeps == [pytest.approx(PAD_HEAD_S + clip.duration_s)]  # returns at the estimated playback end
    assert cam.drain_s == PAD_TAIL_S


async def test_codec_comes_from_options(go2rtc, tmp_path):
    cam, _ = _cam(go2rtc, tmp_path, audio_codec="pcma")
    await cam.play(_clip(tmp_path))
    assert go2rtc.requests[0][2]["src"].endswith("#audio=pcma")


async def test_source_with_spaces_is_refused_before_sending(go2rtc, tmp_path, caplog):
    cam, sleeps = _cam(go2rtc, tmp_path, src_dir="C:/Program Files/cache")
    await cam.play(_clip(tmp_path))
    assert go2rtc.requests == [] and sleeps == []
    assert "spaces" in caplog.text


async def test_rejected_push_is_retried_once_then_logged(go2rtc, tmp_path, caplog):
    go2rtc.fail_posts = 5
    cam, sleeps = _cam(go2rtc, tmp_path)
    await cam.play(_clip(tmp_path))
    assert [r[0] for r in go2rtc.requests] == ["POST", "POST"]
    assert sleeps == [] and "src=ffmpeg:" in caplog.text


async def test_stop_deletes_the_pushed_source(go2rtc, tmp_path):
    started = asyncio.Event()

    async def slow_sleep(s):
        started.set()
        await asyncio.sleep(10)

    cam = Go2rtcCamera("desk_cam", {"go2rtc_url": go2rtc.url, "stream": "cam_xiaomi", "src_dir": "D:/tts",
                                    "local_dir": str(tmp_path / "camera")}, sleep=slow_sleep)
    task = asyncio.create_task(cam.play(_clip(tmp_path)))
    await asyncio.wait_for(started.wait(), 5)
    await cam.stop()
    task.cancel()
    deletes = [r for r in go2rtc.requests if r[0] == "DELETE"]
    assert deletes == [("DELETE", "/api/streams", {"src": "ffmpeg:D:/tts/abc123.cam.wav#audio=opus"})]
