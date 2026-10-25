"""The session panel device (session panel design rev 5 D1, D4; step 6): a real loopback server, requests from
another thread as the web UI makes them, and a whole session driven from the panel alone. Nothing speaks."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request

import anyio
import pytest

from leafi.core.hub import Hub
from leafi.core.storage import Store, loads
from leafi.devices import panel as panel_mod
from leafi.devices.panel import PanelDevice
from leafi.study.harness import loop
from leafi.study.harness.snapshot import snapshot
from tests.fakes import RecordingFace
from tests.test_typed_sources import Typed

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never a proxy for loopback


def http(dev: PanelDevice, method: str, path: str, body=None, *, token: str | None = None, headers=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(f"http://127.0.0.1:{dev.port}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {dev.token if token is None else token}")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with OPENER.open(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


async def call(dev, *args, **kw):
    return await anyio.to_thread.run_sync(lambda: http(dev, *args, **kw))


def device(tmp_path, **options) -> PanelDevice:
    return PanelDevice("panel", {"run_dir": str(tmp_path / "run"), **options})


class State:
    def __init__(self):
        self.n, self.accepting, self.fail = 0, True, False

    def __call__(self) -> dict:
        if self.fail:
            raise RuntimeError("snapshot broke")
        return {"n": self.n, "io": {"accepting": self.accepting}}


async def test_every_request_needs_token_loopback_host_and_no_origin(tmp_path):
    dev = device(tmp_path)
    dev.start(State(), session_id=7)
    try:
        assert (await call(dev, "GET", "/status"))[0] == 200
        assert (await call(dev, "GET", "/status", token=""))[0] == 403
        assert (await call(dev, "GET", "/status", token="wrong"))[0] == 403
        assert (await call(dev, "GET", "/status", headers={"Host": "evil.example:80"}))[0] == 403  # DNS rebinding
        assert (await call(dev, "GET", "/status", headers={"Origin": "http://127.0.0.1:8770"}))[0] == 403
        assert (await call(dev, "GET", "/other"))[0] == 404
    finally:
        await dev.close()


@pytest.mark.parametrize(("body", "code"), [
    ({"session_id": 7, "line": "/explain fox"}, 400),   # not a panel command: it would write evidence
    ({"session_id": 7, "line": "/say /stop"}, 400),     # an answer is never a command
    ({"session_id": 7, "line": "a\r\nb"}, 400),
    ({"session_id": 7, "line": "  "}, 400),
    ({"session_id": 7, "line": "/say " + "x" * 600}, 400),
    ({"session_id": 8, "line": "/skip"}, 409),          # another session's press
    (b"{" * 3000, 413),
    (b"not json", 400),
])
async def test_a_bad_post_is_refused(tmp_path, body, code):
    dev = device(tmp_path)
    dev.start(State(), session_id=7)
    try:
        assert (await call(dev, "POST", "/input", body))[0] == code
        assert dev._queued == []
    finally:
        await dev.close()


async def test_a_post_reaches_the_session_stamped_with_the_snapshot_the_owner_saw(tmp_path):
    dev = device(tmp_path)
    dev.start(State(), session_id=7)
    try:
        version, seen, _ = dev.published
        status, _ = await call(dev, "POST", "/input", {"session_id": 7, "line": "/do break", "seen": seen})
        assert status == 202
        u = await dev.next_utterance(1.0)
        assert (u.text, u.source, u.typed, u.ended_at) == ("/do break", "panel", True, seen)
        status, _ = await call(dev, "POST", "/input", {"session_id": 7, "line": "/skip", "seen": 1.0})  # too old
        u = await dev.next_utterance(1.0)
        assert u.ended_at >= seen and u.ended_at != 1.0  # an implausible stamp becomes the arrival time
    finally:
        await dev.close()


async def test_status_is_served_from_the_published_bytes_even_while_the_loop_is_blocked(tmp_path):
    state = State()
    dev = device(tmp_path)
    dev.start(state, session_id=7)
    try:
        version = dev.published[0]
        status, body = await call(dev, "GET", f"/status?since={version}")
        assert status == 204  # unchanged
        got = {}
        t = threading.Thread(target=lambda: got.setdefault("r", http(dev, "GET", "/status")))
        t.start()
        time.sleep(0.5)  # noqa: ASYNC251 - on purpose: the loop is stuck in a synchronous step (an OCR read)
        t.join(5)
        assert got["r"][0] == 200 and json.loads(got["r"][1])["version"] == version
    finally:
        await dev.close()


async def test_the_trailing_refresh_publishes_the_last_change_and_a_failing_snapshot_keeps_the_old(tmp_path):
    state = State()
    dev = device(tmp_path)
    dev.start(state, session_id=7)
    try:
        state.n = 1
        dev.mark_dirty()  # within 0.2 s of the start's refresh: a trailing one is armed
        state.n = 2
        dev.mark_dirty()
        await anyio.sleep(0.35)
        assert json.loads(dev.published[2])["n"] == 2
        state.fail = True
        dev.refresh()
        assert json.loads(dev.published[2])["n"] == 2
        state.fail, state.accepting = False, False
        dev.refresh()
        assert (await call(dev, "POST", "/input", {"session_id": 7, "line": "/skip"}))[0] == 409  # ending
    finally:
        await dev.close()


async def test_a_port_in_use_or_an_unwritable_run_dir_disables_the_panel_not_the_session(tmp_path):
    class BusyStore:
        def execute(self, *a, **kw):
            raise RuntimeError("database is locked")

        def __getattr__(self, name):
            raise RuntimeError("database is locked")

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        dev = device(tmp_path, port=taken.getsockname()[1])
        dev.start(State(), session_id=7, store=BusyStore())  # the alert write fails too: logged, not raised
        assert dev.dead
        with anyio.move_on_after(0.2) as scope:
            await dev.next_utterance(None)  # delivers nothing, forever
        assert scope.cancelled_caught
        await dev.close()
    (tmp_path / "blocked").write_text("a file where the run dir should be")
    dev = PanelDevice("panel", {"run_dir": str(tmp_path / "blocked" / "run")})
    dev.start(State(), session_id=7)
    assert dev.dead
    await dev.close()


async def test_close_is_idempotent_frees_the_port_and_removes_only_its_own_file(tmp_path):
    never = device(tmp_path)
    with anyio.fail_after(2):
        await never.close()  # never started: no hang
    dev = device(tmp_path)
    other = tmp_path / "run" / "study-panel-1.json"
    dev.start(State(), session_id=7)
    other.write_text(json.dumps({"schema": 1, "pid": os.getpid(), "started_at": "x"}))  # a live session's
    own = tmp_path / "run" / f"study-panel-{os.getpid()}.json"
    info = json.loads(own.read_text())
    assert info["port"] == dev.port and info["session_id"] == 7 and info["token"] == dev.token
    port = dev.port
    await dev.close()
    await dev.close()
    assert not own.exists() and other.exists()
    with socket.socket() as s, pytest.raises(OSError):
        s.settimeout(1)
        s.connect(("127.0.0.1", port))


def test_runtime_files_are_read_and_swept_by_their_process(tmp_path):
    import psutil

    run = tmp_path / "run"
    run.mkdir()
    mine = {"schema": 1, "pid": os.getpid(), "create_time": psutil.Process().create_time(), "started_at": "b"}
    (run / "study-panel-1.json").write_text(json.dumps(mine))
    (run / "study-panel-2.json").write_text(json.dumps(mine | {"pid": 2 ** 22 + 7, "started_at": "a"}))  # gone
    (run / "study-panel-3.json").write_text(json.dumps(mine | {"create_time": 1.0}))  # a reused pid
    (run / "study-panel-4.json").write_text("{partial")
    assert [i["started_at"] for i in panel_mod.runtime_files(run)] == ["b", "b", "a"]  # newest first
    panel_mod.sweep(run)
    assert sorted(p.name for p in run.iterdir()) == ["study-panel-1.json", "study-panel-4.json"]


async def test_a_whole_session_is_driven_from_the_panel_alone(settings):
    dev = PanelDevice("panel", {"run_dir": str(settings.data_dir / "run")})
    console = Typed([], "console")  # nobody types: the panel leads every step
    face = RecordingFace()
    hub = Hub(faces={"f": face, "panel": dev}, policy="none", listeners={"console": console, "panel": dev})
    env = loop.Env(store=Store(settings.db_path), hub=hub, settings=settings, listener=console,
                   book_title="Fixture", page_text="The fox ran home. It was late and dark.", page_number=1,
                   learner="Ada")

    def built(s, w):
        dev.start(lambda: snapshot(s, w), session_id=s.session_id, store=s.store)
        s.hooks.append(dev.mark_dirty)
        w.inputs.on_change = dev.mark_dirty

    env.on_built = built

    async def status() -> dict:
        code, body = await call(dev, "GET", "/status")
        return json.loads(body) if code == 200 else {}

    async def until(test) -> dict:
        while True:
            sh = await status()
            if sh and test(sh):
                return sh
            await anyio.sleep(0.05)

    async def owner():
        await until(lambda sh: (sh.get("activity") or {}).get("kind") == "read_listen" and sh["io"]["listening"])
        sh = await status()
        await call(dev, "POST", "/input", {"session_id": sh["session_id"], "line": "/do break",
                                           "seen": sh["publish_t"]})
        sh = await until(lambda sh: (sh.get("activity") or {}).get("kind") == "break")
        await call(dev, "POST", "/input", {"session_id": sh["session_id"], "line": "/stop"})

    with anyio.fail_after(20):
        async with anyio.create_task_group() as tg:
            tg.start_soon(owner)
            sid = await loop.run_session(env)
        await dev.close()
    acts = env.store.all("SELECT kind, status, params, outcome FROM activities WHERE session_id=? ORDER BY id",
                         (sid,))
    assert [(r["kind"], r["status"]) for r in acts] == [("read_listen", "completed"), ("break", "stopped")]
    assert loads(acts[0]["outcome"], {})["ended_by"] == "do" and loads(acts[1]["params"], {})["by"] == "panel"
    summ = loads(env.store.one("SELECT summary FROM reading_sessions WHERE id=?", (sid,))["summary"], {})
    assert [x["command"] for x in summ["panel_lines"]] == ["do break", "stop"]
    assert not list((settings.data_dir / "run").glob("study-panel-*.json"))  # the file went with the session
