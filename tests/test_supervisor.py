"""ADR-0016 supervisor: the per-service policy, observations, dependency suppression and the rearm endpoint."""

from __future__ import annotations

import asyncio
import functools
import io
import subprocess
import sys

import httpx
import pytest
from PIL import Image

from leafi.core import storage
from leafi.core.storage import Store
from leafi.ops import supervisor
from leafi.ops.supervisor import BAD, GOOD, IDLE, Service, ServicePolicy

CameraPolicy = functools.partial(ServicePolicy, service="camera", grace_s=90.0)
STATE = "SELECT kills, gave_up, latch FROM service_state WHERE service = 'camera'"


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
    assert store.one(STATE)[:] == (3, 1, "down")


def test_ten_good_minutes_reset_the_budget_and_send_one_up_row(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 12)
    _run(p, t, GOOD, 9)
    assert _rows(store) == [("camera", "down", "restart_gave_up")]  # 9 min is not enough
    _run(p, t, GOOD, 3)
    assert _rows(store)[-1] == ("camera", "up", "recovered")
    assert store.one(STATE)[:] == (0, 0, "up")
    _run(p, t, GOOD, 20)
    assert len(_rows(store)) == 2  # no repeated up rows


def test_rearm_restarts_as_attempt_one_and_never_adds_a_second_down_row(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 12)
    assert p.rearm(t.mono) is True
    assert store.one(STATE)["kills"] == 1
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


def test_the_budget_survives_a_supervisor_restart(store):
    t = T()
    p = CameraPolicy(store)
    p.started(t.mono - 1000)
    _run(p, t, BAD, 5)  # two restarts charged
    again = CameraPolicy(store)
    again.started(t.mono - 1000)
    assert len(_run(again, t, BAD, 10)) == 1  # only one left


def test_each_service_has_its_own_budget_and_alert_key(store):
    t = T()
    cam = CameraPolicy(store)
    agent = ServicePolicy(store, service="habit-agent", grace_s=90.0)
    for p in (cam, agent):
        p.started(t.mono - 1000)
    for _ in range(12):
        t.tick()
        if agent.step(BAD, t.mono, t.wall):
            agent.started(t.mono)
        cam.step(GOOD, t.mono, t.wall)
    assert _rows(store) == [("habit-agent", "down", "restart_gave_up")]
    assert store.one(STATE)[:] == (0, 0, "up")


def test_migration_moves_the_camera_budget_into_service_state(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(storage, "MIGRATIONS", storage.MIGRATIONS[:3])
    old = Store(path)
    old.insert("watchdog_state", id=1, kills=2, gave_up=0, latch="down", updated_at="x")
    old.close()
    monkeypatch.undo()
    new = Store(path)
    assert new.one(STATE)[:] == (2, 0, "down")
    assert new.one("SELECT name FROM sqlite_master WHERE name = 'watchdog_state'") is None


# ---------------------------------------------------------------- one poll over all services


class FakeService:
    def __init__(self, name: str, obs: str, depends_docker: bool = False) -> None:
        self.observed = 0
        self.recovered = 0

        async def observe() -> str:
            self.observed += 1
            return obs

        async def recover() -> None:
            self.recovered += 1

        self.svc = Service(name, grace_s=60.0, observe=observe, recover=recover, depends_docker=depends_docker)


async def test_containers_are_idle_while_docker_is_down(store):
    t = T()
    docker = FakeService("docker", BAD)
    frigate = FakeService("frigate", BAD, depends_docker=True)
    services = [docker.svc, frigate.svc]
    policies = {s.name: ServicePolicy(store, s.name, s.grace_s) for s in services}
    for p in policies.values():
        p.started(t.mono - 1000)
    for _ in range(12):
        t.tick()
        await supervisor.poll(services, policies, t.mono, t.wall)
    assert frigate.observed == 0 and frigate.recovered == 0  # suppressed, never restarted behind a dead engine
    assert await supervisor.poll(services, policies, t.mono, t.wall) == {"docker": BAD, "frigate": IDLE}
    assert docker.recovered == 3
    assert _rows(store) == [("docker", "down", "restart_gave_up")]


async def test_a_failed_recovery_is_logged_and_does_not_stop_the_poll(store):
    t = T()
    broken = FakeService("frigate", BAD)

    async def boom() -> None:
        raise RuntimeError("compose failed")

    broken.svc.recover = boom
    other = FakeService("mosquitto", BAD)
    services = [broken.svc, other.svc]
    policies = {s.name: ServicePolicy(store, s.name, s.grace_s) for s in services}
    for p in policies.values():
        p.started(t.mono - 1000)
    for _ in range(3):
        t.tick()
        await supervisor.poll(services, policies, t.mono, t.wall)
    assert other.recovered == 1


async def test_mosquitto_probe_is_a_tcp_connect():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    assert await supervisor.tcp_probe("127.0.0.1", port) == GOOD
    server.close()
    await server.wait_closed()
    assert await supervisor.tcp_probe("127.0.0.1", port) == BAD


async def test_http_probe_is_good_only_on_200():
    def handler(req):
        return httpx.Response(200 if req.url.path == "/ok" else 503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await supervisor.http_probe(c, "http://x/ok") == GOOD
        assert await supervisor.http_probe(c, "http://x/down") == BAD


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
    assert await supervisor.observe_camera(client, settings) == expected


async def test_observe_never_fetches_a_frame_without_demand(settings):
    client, seen = _go2rtc({"cam_xiaomi": {"producers": [{"remote_addr": "x"}], "consumers": None}}, _jpeg())
    assert await supervisor.observe_camera(client, settings) == IDLE
    assert "/api/frame.jpeg" not in seen


# ---------------------------------------------------------------- rearm endpoint and Job Object


async def test_rearm_endpoint_accepts_only_post_rearm_for_a_known_service():
    called = []
    server = await supervisor.serve_rearm("127.0.0.1", 0, called.append, {"camera", "frigate"})
    port = server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient() as c:
        assert (await c.post(f"http://127.0.0.1:{port}/rearm")).status_code == 200
        assert (await c.post(f"http://127.0.0.1:{port}/rearm?service=frigate")).status_code == 200
        assert (await c.post(f"http://127.0.0.1:{port}/rearm?service=nope")).status_code == 404
        assert (await c.get(f"http://127.0.0.1:{port}/rearm")).status_code == 404
        assert (await c.post(f"http://127.0.0.1:{port}/alert", content=b"x")).status_code == 404
    server.close()
    await server.wait_closed()
    assert called == ["camera", "frigate"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects")
def test_closing_the_job_kills_its_process_tree():
    job = supervisor.Job()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    job.assign(child)
    job.close()
    try:
        child.wait(5)
    except subprocess.TimeoutExpired:
        child.kill()
        pytest.fail("the child outlived its job")
