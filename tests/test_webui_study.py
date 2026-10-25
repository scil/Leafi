"""The web UI's Reading tab (session panel design rev 5 D5, D6; step 7): the real web UI server on an ephemeral port
proxying to a real `PanelDevice`, the action table, the request checks, the read-only database fallback and the
safe-point note on the page. Nothing speaks."""

from __future__ import annotations

import http.client
import json
import os
import socket
import threading

import anyio
import portalocker
import pytest

from agent.webui.__main__ import make_server
from leafi.core.storage import Store
from leafi.devices.panel import PanelDevice
from tests import seed


@pytest.fixture
def web(settings):
    httpd = make_server("127.0.0.1", 0, env_path=settings.data_dir / ".env", data_dir=settings.data_dir,
                        leafi_settings=lambda: settings)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method, path, body=None, *, token=True, origin=True, **headers):
    port = httpd.server_address[1]
    hdrs = {"Host": f"127.0.0.1:{port}"}
    if token:
        hdrs["X-Leafi-Token"] = httpd.token
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        if origin is True:
            hdrs["Origin"] = f"http://127.0.0.1:{port}"
        elif origin:
            hdrs["Origin"] = origin
    hdrs.update({k.replace("_", "-"): v for k, v in headers.items()})
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=None if body is None else json.dumps(body), headers=hdrs)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, (json.loads(data) if data and r.getheader("Content-Type", "").startswith("application/json")
                      else data)


async def acall(httpd, *args, **kw):
    return await anyio.to_thread.run_sync(lambda: call(httpd, *args, **kw))


def live_panel(settings, session_id=7) -> PanelDevice:
    dev = PanelDevice("panel", {"run_dir": str(settings.data_dir / "run")})
    dev.start(lambda: {"io": {"accepting": True}, "learner": {"kind": "learner", "name": "Ada"}},
              session_id=session_id)
    return dev


def test_the_page_has_the_tab_and_the_safe_point_note(web):
    status, page = call(web, "GET", "/")
    assert status == 200
    assert b'id="tab-read"' in page and b"Takes effect at the next safe point" in page
    assert b"not during setup" in page and b"page scan (OCR) always finishes first" in page


def test_status_needs_the_page_token(web):
    assert call(web, "GET", "/api/study/status", token=False)[0] == 403


def test_with_no_session_the_last_one_comes_from_the_database_read_only(web, settings):
    status, view = call(web, "GET", "/api/study/status")
    assert (status, view) == (200, {"state": "none", "last": None})  # no database: none is created
    assert not settings.db_path.exists()
    store = Store(settings.db_path)
    learner = seed.learner(store)
    book, _, _ = seed.book_page(store, "The fox ran home.")
    seed.session(store, book, learner_id=learner)
    store.close()
    status, view = call(web, "GET", "/api/study/status")
    assert view["state"] == "none" and view["last"]["learner"]["kind"] == "learner"
    users = settings.db_path.with_name(settings.db_path.name + ".users")
    with portalocker.Lock(str(users), flags=portalocker.LOCK_EX | portalocker.LOCK_NB, fail_when_locked=True):
        pass  # the tab holds no lock between polls: `leafi migrate` can take it


def test_a_broken_database_is_shown_as_an_error(web, settings):
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.db_path.write_bytes(b"not a database at all, just bytes" * 40)
    status, view = call(web, "GET", "/api/study/status")
    assert status == 200 and view["state"] == "db_error"


async def test_a_live_session_is_proxied_and_unchanged_is_204(web, settings):
    dev = live_panel(settings)
    try:
        status, view = await acall(web, "GET", "/api/study/status")
        assert status == 200 and view["state"] == "live" and view["session_id"] == 7
        assert view["learner"]["name"] == "Ada" and "token" not in json.dumps(view)  # the token stays server-side
        status, _ = await acall(web, "GET", f"/api/study/status?since={view['version']}")
        assert status == 204
        status, _ = await acall(web, "GET", "/api/study/status?since=8:" + view["version"].split(":")[1])
        assert status == 200  # another session's version is never "unchanged"
    finally:
        await dev.close()


async def test_a_live_process_that_does_not_answer_is_busy(web, settings):
    import psutil

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]  # closed again: nothing answers there
    run = settings.data_dir / "run"
    run.mkdir(parents=True)
    (run / "study-panel-1.json").write_text(json.dumps({
        "schema": 1, "pid": os.getpid(), "create_time": psutil.Process().create_time(), "port": dead_port,
        "token": "t", "session_id": 9, "started_at": "now"}))
    status, view = await acall(web, "GET", "/api/study/status")
    assert view == {"state": "busy", "session_id": 9}
    assert (run / "study-panel-1.json").exists()  # the web UI never deletes a runtime file


async def test_each_action_becomes_one_line_of_the_table(web, settings):
    dev = live_panel(settings)
    try:
        cases = [({"action": "answer", "text": "it was dark"}, "/say it was dark"),
                 ({"action": "do", "text": "break"}, "/do break"),
                 ({"action": "ease", "text": "good"}, "/good"),
                 ({"action": "next_page"}, "/next"),
                 ({"action": "fix", "old": "fax", "text": "fox"}, "/fix fax fox")]
        for body, line in cases:
            status, res = await acall(web, "POST", "/api/study/action", {"session_id": 7, **body})
            assert (status, res["line"]) == (200, line)
            assert (await dev.next_utterance(1.0)).text == line
        status, res = await acall(web, "POST", "/api/study/action",
                                  {"session_id": 7, "action": "page", "n": 3, "text": "The moon was up."})
        assert status == 200
        path = res["line"].split(" --text ")[1]
        assert os.path.isabs(path) and str(settings.cache_dir.resolve()) in path
        assert await anyio.Path(path).read_text(encoding="utf-8") == "The moon was up.\n"
    finally:
        await dev.close()


@pytest.mark.parametrize("body", [
    {"action": "answer", "text": "/stop"},        # an answer is never a command
    {"action": "answer", "text": "two\nlines"},
    {"action": "do", "text": "wait"},             # harness-internal
    {"action": "do", "text": "flying"},
    {"action": "explain", "text": "fox"},         # not on the panel: it writes evidence
    {"action": "fix", "old": "two words", "text": "x"},
    {"action": "page", "n": "3", "text": "x"},
])
async def test_an_action_outside_the_table_is_refused(web, settings, body):
    dev = live_panel(settings)
    try:
        status, _ = await acall(web, "POST", "/api/study/action", {"session_id": 7, **body})
        assert status == 400 and dev._queued == []
    finally:
        await dev.close()


async def test_an_action_goes_only_to_the_session_shown(web, settings):
    dev = live_panel(settings, session_id=8)  # a newer session than the page showed
    try:
        status, res = await acall(web, "POST", "/api/study/action", {"session_id": 7, "action": "stop"})
        assert (status, res["error"]) == (409, "that session has ended") and dev._queued == []
    finally:
        await dev.close()


async def test_an_action_needs_our_origin_and_no_cross_site_fetch(web, settings):
    dev = live_panel(settings)
    port = web.server_address[1]
    try:
        body = {"session_id": 7, "action": "skip"}
        assert (await acall(web, "POST", "/api/study/action", body, origin=None))[0] == 403  # a missing Origin
        assert (await acall(web, "POST", "/api/study/action", body, origin="http://127.0.0.1:15000"))[0] == 403
        assert (await acall(web, "POST", "/api/study/action", body, Sec_Fetch_Site="same-site"))[0] == 403
        assert (await acall(web, "POST", "/api/study/action", body, Sec_Fetch_Site="same-origin"))[0] == 200
        assert (await acall(web, "POST", "/api/study/action", body, token=False))[0] == 403
        assert port  # every refusal above was the web UI's own: nothing reached the session
        assert dev._queued == ["/skip"]
    finally:
        await dev.close()
