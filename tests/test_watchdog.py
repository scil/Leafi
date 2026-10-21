"""ADR-0016 watchdog: the camera state machine, the observation step and the rearm endpoint."""

from __future__ import annotations

import io
import subprocess
import sys

import httpx
import pytest
from PIL import Image

from leafi.core.storage import Store
from leafi.ops import watchdog
from leafi.ops.watchdog import BAD, GOOD, IDLE, CameraPolicy


class T:
    """Monotonic and wall clocks that advance together unless a sleep is simulated."""

    def __init__(self) -> None:
        self.mono = 100.0
        self.wall = 1_000_000.0

    def tick(self, s: float = 60.0) -> None:
        self.mono += s
        self.wall += s


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _rows(store):
    return [tuple(r) for r in store.all("SELECT key, state, reason FROM alert_outbox ORDER BY id")]


def _run(policy: CameraPolicy, t: T, obs: str, polls: int) -> list[int]:
    """Feed `polls` observations one minute apart; return the poll indexes at which a restart was asked."""
    asked = []
    for i in range(polls):
        t.tick()
        if policy.step(obs, t.mono, t.wall):
            asked.append(i)
            policy.started(t.mono)
    return asked


def test_a_dead_camera_gets_three_restarts_then_one_gave_up_alert(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)  # long past the start grace
    asked = _run(p, t, BAD, 30)
    assert len(asked) == 3
    assert asked == [1, 4, 7]  # BAD, BAD -> restart; 90 s grace swallows one poll; then BAD, BAD again
    assert _rows(store) == [("camera", "down", "restart_gave_up")]
    assert store.one("SELECT kills, gave_up, latch FROM watchdog_state")[:] == (3, 1, "down")


def test_ten_good_minutes_reset_the_budget_and_send_one_up_row(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 12)
    _run(p, t, GOOD, 9)
    assert _rows(store) == [("camera", "down", "restart_gave_up")]  # 9 min is not enough
    _run(p, t, GOOD, 3)
    assert _rows(store)[-1] == ("camera", "up", "recovered")
    assert store.one("SELECT kills, gave_up, latch FROM watchdog_state")[:] == (0, 0, "up")
    _run(p, t, GOOD, 20)
    assert len(_rows(store)) == 2  # no repeated up rows


def test_rearm_restarts_as_attempt_one_and_never_adds_a_second_down_row(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 12)
    assert p.rearm(t.mono) is True
    assert store.one("SELECT kills FROM watchdog_state")["kills"] == 1
    p.started(t.mono)
    asked = _run(p, t, BAD, 15)
    assert len(asked) == 2  # attempts 2 and 3, then gave up again
    assert _rows(store) == [("camera", "down", "restart_gave_up")]  # same outage, one row


def test_idle_and_single_bad_polls_never_restart(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    pattern = [GOOD, BAD, GOOD, IDLE, BAD, IDLE, BAD, GOOD] * 5
    for obs in pattern:
        t.tick()
        assert p.step(obs, t.mono, t.wall) is False
    assert _rows(store) == []


def test_bad_polls_inside_the_start_grace_do_not_count(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono)
    t.tick(30)
    assert p.step(BAD, t.mono, t.wall) is False
    t.tick(30)
    assert p.step(BAD, t.mono, t.wall) is False  # 60 s after start: still in grace
    t.tick(60)
    assert p.step(BAD, t.mono, t.wall) is False  # first counted BAD
    t.tick(60)
    assert p.step(BAD, t.mono, t.wall) is True


def test_a_sleep_is_neither_an_outage_nor_healthy_time(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 12)  # gave up, latch down
    t.mono += 8 * 3600
    t.wall += 8 * 3600  # suspended 8 h
    assert p.step(GOOD, t.mono, t.wall) is False
    t.tick()
    p.step(GOOD, t.mono, t.wall)
    assert _rows(store)[-1][1] == "down"  # the sleep did not count as ten good minutes
    t.mono += 3600
    t.wall += 3600
    assert p.step(BAD, t.mono, t.wall) is False  # resume grace
    t.tick()
    assert p.step(BAD, t.mono, t.wall) is False


def test_the_budget_survives_a_watchdog_restart(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 5)  # two restarts charged
    again = CameraPolicy(store)
    again.started(t.mono - 1000)
    assert len(_run(again, t, BAD, 10)) == 1  # only one left


# ---------------------------------------------------------------- observe()


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (90, 120, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _go2rtc(streams: dict | None, frame: bytes = b"", frigate: dict | None = None):
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.url.port == 2984:
            if streams is None:
                raise httpx.ConnectError("refused")
            if req.url.path == "/api/streams":
                return httpx.Response(200, json=streams)
            if req.url.path == "/api/frame.jpeg":
                return httpx.Response(200, content=frame)
        if req.url.port == 15000:
            if frigate is None:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=frigate)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


LIVE = {"producers": [{"remote_addr": "cs2+tcp", "bytes_recv": 10}], "consumers": [{"remote_addr": "x"}]}


@pytest.mark.parametrize("streams, frame, frigate, expected", [
    (None, b"", None, BAD),                                                         # API down
    ({"cam_xiaomi": {"producers": None, "consumers": None}}, b"", None, IDLE),      # lazy, nobody wants it
    ({"cam_xiaomi": LIVE}, _jpeg(), None, GOOD),
    ({"cam_xiaomi": LIVE}, b"", None, BAD),                                         # TD-25: 200 with 0 bytes
    ({"cam_xiaomi": {"producers": [{"id": 1}], "consumers": None}}, b"", {"cameras": {"hallway": {}}}, BAD),
])
async def test_observe_classifies_one_poll(settings, streams, frame, frigate, expected):
    client, _ = _go2rtc(streams, frame, frigate)
    assert await watchdog.observe(client, settings) == expected


async def test_observe_never_fetches_a_frame_without_demand(settings):
    client, seen = _go2rtc({"cam_xiaomi": {"producers": [{"remote_addr": "x"}], "consumers": None}}, _jpeg())
    assert await watchdog.observe(client, settings) == IDLE
    assert "/api/frame.jpeg" not in seen


# ---------------------------------------------------------------- rearm endpoint and Job Object


async def test_rearm_endpoint_accepts_only_post_rearm():
    called = []
    server = await watchdog.serve_rearm("127.0.0.1", 0, lambda: called.append(1))
    port = server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient() as c:
        assert (await c.post(f"http://127.0.0.1:{port}/rearm")).status_code == 200
        assert (await c.get(f"http://127.0.0.1:{port}/rearm")).status_code == 404
        assert (await c.post(f"http://127.0.0.1:{port}/alert", content=b"x")).status_code == 404
    server.close()
    await server.wait_closed()
    assert called == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects")
def test_closing_the_job_kills_its_process_tree():
    job = watchdog.Job()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    job.assign(child)
    job.close()
    try:
        child.wait(5)
    except subprocess.TimeoutExpired:
        child.kill()
        pytest.fail("the child outlived its job")
