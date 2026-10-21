"""The task editor's `.env` API and its request checks (design §6), against the real server on an ephemeral port."""

import http.client
import json
import logging
import threading

import pytest

from agent.webui.__main__ import make_server
from leafi import envedit

CANARY = "canary-secret-987"


@pytest.fixture
def server(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(f"ASR_THREADS=4\nTELEGRAM_BOT_TOKEN={CANARY}\n".encode())
    httpd = make_server("127.0.0.1", 0, env_path=env, data_dir=tmp_path / "data")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method, path, body=None, **headers):
    port = httpd.server_address[1]
    hdrs = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        hdrs.update({"Content-Type": "application/json", "X-Leafi-Token": httpd.token})
    hdrs.update({k.replace("_", "-"): v for k, v in headers.items() if v is not None})
    for k in [k for k, v in headers.items() if v is None]:
        hdrs.pop(k.replace("_", "-"), None)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=None if body is None else json.dumps(body), headers=hdrs)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def test_page_carries_the_token_and_the_secret_never_leaves(server, caplog):
    caplog.set_level(logging.DEBUG)
    status, page = call(server, "GET", "/")
    assert status == 200 and server.token.encode() in page
    status, body = call(server, "GET", "/api/env")
    assert status == 200 and CANARY.encode() not in body
    digest = json.loads(body)["digest"]
    status, body = call(server, "POST", "/api/env", {"digest": digest, "ops": {
        "ASR_THREADS": {"op": "set", "value": "6"}, "TELEGRAM_BOT_TOKEN": {"op": "set", "value": "new-" + CANARY}}})
    assert status == 200 and json.loads(body)["ok"] is True
    assert CANARY.encode() not in body
    assert CANARY not in caplog.text
    assert b"ASR_THREADS=6" in server.env_path.read_bytes()


def test_stale_digest_is_409_and_bad_value_writes_nothing(server):
    before = server.env_path.read_bytes()
    status, _ = call(server, "POST", "/api/env", {"digest": "0" * 64, "ops": {"ASR_THREADS": {"op": "set", "value": "6"}}})
    assert status == 409
    digest = json.loads(call(server, "GET", "/api/env")[1])["digest"]
    status, body = call(server, "POST", "/api/env", {"digest": digest, "ops": {
        "ASR_THREADS": {"op": "set", "value": "x"}, "VAD_THRESHOLD": {"op": "set", "value": "0.3"}}})
    assert status == 200 and json.loads(body)["ok"] is False
    assert server.env_path.read_bytes() == before


def test_privacy_change_needs_its_confirmation(server):
    digest = json.loads(call(server, "GET", "/api/env")[1])["digest"]
    ops = {"BOOK_LOOKUP": {"op": "set", "value": "openlibrary"}}
    body = json.loads(call(server, "POST", "/api/env", {"digest": digest, "ops": ops})[1])
    assert "BOOK_LOOKUP" in body["errors"]
    body = json.loads(call(server, "POST", "/api/env", {"digest": digest, "ops": ops,
                                                      "confirm": {"BOOK_LOOKUP": envedit.confirmation("openlibrary")}})[1])
    assert body["ok"] is True


@pytest.mark.parametrize("path", ["/api/env", "/api/tasks"])
@pytest.mark.parametrize("bad", [
    {"Host": "evil.example:8770"},
    {"Content_Type": "text/plain"},
    {"Origin": "http://evil.example"},
    {"X_Leafi_Token": "wrong"},
    {"X_Leafi_Token": None},
])
def test_request_checks_reject_cross_site_posts(server, path, bad):
    before = server.env_path.read_bytes()
    status, body = call(server, "POST", path, {"digest": "x", "ops": {}}, **bad)
    assert status == 403 and body == b""
    assert server.env_path.read_bytes() == before


def test_get_checks_the_host_too(server):
    assert call(server, "GET", "/", Host="rebound.example:80")[0] == 403
    assert call(server, "GET", "/api/env", Host="rebound.example:80")[0] == 403
