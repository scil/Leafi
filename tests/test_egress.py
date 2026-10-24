"""The egress pipeline (ADR-0018 §2, M5 design D5–D9): `prepare` and the mediating transport, with the guard
enforcing, against a real HTTP server on a loopback port marked as a gateway port (so every byte needs a grant
and nothing leaves the machine). The first case is the real-SDK positive control of D6: `anthropic` 1.17 builds
the body itself and the transport must accept exactly that request and nothing else."""

from __future__ import annotations

import asyncio
import json

import anthropic
import httpx2
import pytest

from leafi.core import learner_store, netguard
from leafi.core.storage import Store
from leafi.privacy import destinations as dests
from leafi.privacy import egress as eg
from leafi.privacy import secret
from leafi.privacy import settings as privacy
from leafi.privacy.egress import Outgoing, Text


class FakeServer:
    """HTTP/1.1 on 127.0.0.1, one request per connection; `replies` is a queue of (status, json, headers)."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.replies: list[tuple[int, object, dict]] = []

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            line = (await r.readline()).decode()
            headers = {}
            while (h := (await r.readline()).decode().strip()):
                k, v = h.split(":", 1)
                headers[k.strip().lower()] = v.strip()
            body = await r.readexactly(int(headers.get("content-length", 0)))
            method, target, _ = line.split(" ", 2)
            self.requests.append({"method": method, "target": target, "headers": headers, "body": body})
            status, payload, extra = self.replies.pop(0) if self.replies else (200, _MESSAGE("ok"), {})
            data = json.dumps(payload).encode()
            head = [f"HTTP/1.1 {status} X", "content-type: application/json", f"content-length: {len(data)}",
                    "connection: close", *(f"{k}: {v}" for k, v in extra.items())]
            w.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
            await w.drain()
        finally:
            w.close()

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()


def _MESSAGE(text: str) -> dict:
    return {"id": "m", "type": "message", "role": "assistant", "model": "claude-x",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}}


@pytest.fixture
async def server():
    s = FakeServer()
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
def world(settings, server):
    """A learner who may send text, an enforcing guard with the server's port as a gateway, and egress."""
    secret._forget_cache()
    store = Store(settings.db_path)
    rocco = learner_store.create(store, "Rocco")
    privacy.set_school(store, rocco, "James McKinney Elementary School")
    before = netguard.policy()
    netguard.configure(netguard.Policy(mode="enforce", gateway_ports=frozenset({server.port})))
    fake = dests.Destination("fake", "http", frozenset({"127.0.0.1"}), server.port,
                             frozenset({"generate", "word", "notify", "tts", "media", dests.OPS}), "cloud",
                             dests.ANTHROPIC_HEADERS)
    local = dests.Destination("local", "http", frozenset({"127.0.0.1"}), server.port, frozenset({"generate"}),
                              "local")
    e = eg.Egress(settings, registry={"fake": fake, "local": local}, env_file=None)
    yield type("W", (), {"store": store, "rocco": rocco, "egress": e, "server": server, "settings": settings})
    e.close()
    store.close()
    netguard.configure(before)


def _sdk(w) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key="test-key", base_url=f"http://127.0.0.1:{w.server.port}",
                                    max_retries=0, open_telemetry=False, http_client=w.egress.client("fake"))


def _brain_body(w, text: str) -> dict:
    return {"model": "claude-x", "max_tokens": 50, "system": "You help a child read.",
            "messages": [{"role": "user", "content": Text(text, "learner", (w.rocco,))}]}


def _log(w):
    return [tuple(r) for r in w.store.all("SELECT destination, purpose, learner_id, status, transmitted_attempts "
                                          "FROM egress_log ORDER BY id")]


async def test_real_sdk_request_is_accepted_and_names_never_leave(world):
    w = world
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "Rocco read well.")),
                         learner_id=w.rocco)
    sur = next(iter(p.mapping.back))
    w.server.replies.append((200, _MESSAGE(f"Great job, {sur}!"), {}))
    r = await _sdk(w).messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    (req,) = w.server.requests
    assert b"Rocco" not in req["body"] and sur.encode() in req["body"]
    assert eg.TOKEN_HEADER not in req["headers"]
    assert json.loads(req["body"]) == p.json
    assert p.reverse(r.content[0].text) == "Great job, Rocco!"
    assert _log(w) == [("fake", "generate", w.rocco, "sent", 1)]


async def test_a_spent_token_is_refused_for_any_request(world):
    w = world
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    sdk = _sdk(w)
    await sdk.messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    with pytest.raises(anthropic.PermissionDeniedError):
        await sdk.messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    assert len(w.server.requests) == 1


async def test_a_body_or_header_the_adapter_did_not_prepare_is_refused(world):
    w = world
    sdk = _sdk(w)
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    changed = {**p.json, "messages": [{"role": "user", "content": "Rocco says hi"}]}
    with pytest.raises(anthropic.PermissionDeniedError, match="body differs"):
        await sdk.messages.create(**changed, extra_headers={eg.TOKEN_HEADER: p.token_id})
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    with pytest.raises(anthropic.PermissionDeniedError, match="header 'x-note'"):
        await sdk.messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id, "x-note": "Rocco"})
    with pytest.raises(anthropic.PermissionDeniedError, match="no attempt token"):
        await sdk.messages.create(**p.json)
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json={**_brain_body(w, "hi"),
                                                                                "flag": True}),
                         learner_id=w.rocco)
    kwargs = {k: v for k, v in p.json.items() if k != "flag"}
    with pytest.raises(anthropic.PermissionDeniedError, match="body differs"):  # true is not 1
        await sdk.messages.create(**kwargs, extra_body={"flag": 1}, extra_headers={eg.TOKEN_HEADER: p.token_id})
    assert w.server.requests == []
    assert [r[3:] for r in _log(w)] == [("failed", 0)] * 3  # refused before any reservation


async def test_learner_words_need_cloud_text_and_a_school_answer(world):
    w = world
    leo = learner_store.create(w.store, "Leo")
    body = {"messages": [{"role": "user", "content": Text("Leo here", "learner", (leo,))}]}
    with pytest.raises(eg.Refused, match="no school answer"):
        w.egress.prepare("fake", "generate", Outgoing(json=body), learner_id=leo)
    privacy.set_school(w.store, leo, None)
    privacy.write(w.store, leo, "cloud.text", False)
    with pytest.raises(eg.Refused, match="cloud.text off"):
        w.egress.prepare("fake", "generate", Outgoing(json=body), learner_id=leo)
    with pytest.raises(eg.Refused, match="without its source"):
        w.egress.prepare("fake", "generate", Outgoing(json={"t": Text("x", "learner")}), learner_id=w.rocco)
    w.egress.prepare("fake", "generate", Outgoing(json={"t": Text("x", "parent")}), learner_id=w.rocco)  # default on
    w.settings.cloud_parent_text = False
    with pytest.raises(eg.Refused, match="parent text"):
        w.egress.prepare("fake", "generate", Outgoing(json={"t": Text("x", "parent")}), learner_id=w.rocco)
    local = w.egress.prepare("local", "generate", Outgoing(json=body), learner_id=leo)  # a local model may read it
    assert b"Leo here" in local.body


async def test_a_change_between_prepare_and_send_refuses(world):
    w = world
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    w.store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('Grandma Lu', 'name', 't')")
    with pytest.raises(anthropic.PermissionDeniedError, match="protected names changed"):
        await _sdk(w).messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    privacy.write(w.store, w.rocco, "cloud.text", False)
    with pytest.raises(anthropic.PermissionDeniedError, match="privacy settings of learner"):
        await _sdk(w).messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    assert w.server.requests == []


async def test_one_mediator_retry_on_5xx_and_none_by_the_adapter(world):
    w = world
    w.server.replies += [(503, {"type": "error", "error": {"type": "overloaded_error", "message": "x"}}, {}),
                         (200, _MESSAGE("ok"), {})]
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    r = await _sdk(w).messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    assert r.content[0].text == "ok" and len(w.server.requests) == 2
    assert _log(w) == [("fake", "generate", w.rocco, "sent", 2)]


async def test_a_redirect_is_not_followed_and_media_is_refused(world):
    w = world
    w.server.replies.append((302, {}, {"location": "http://192.0.2.1/elsewhere"}))
    p = w.egress.prepare("fake", "word", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    async with w.egress.client("fake") as c:
        r = await c.send(p.request())
    assert r.status_code == 403 and "redirect" in r.json()["refused"]
    with pytest.raises(eg.Refused, match="media"):
        w.egress.prepare("fake", "media", Outgoing(), learner_id=w.rocco)
    with pytest.raises(eg.Refused, match="no destination"):
        w.egress.prepare("nowhere", "generate", Outgoing(), learner_id=w.rocco)
    with pytest.raises(eg.Refused, match="needs the learner"):
        w.egress.prepare("fake", "generate", Outgoing())


async def test_path_fields_are_filtered_before_quoting(world):
    """Bark puts the notification text in the URL path (design D6)."""
    w = world
    p = w.egress.prepare("fake", "notify", Outgoing(method="GET", path="/key/{title}/{body}",
                                                    path_fields={"title": "Leafi",
                                                                 "body": Text("Rocco read 3 pages", "derived_from_learner",
                                                                              (w.rocco,))}),
                         learner_id=w.rocco)
    async with w.egress.client("fake") as c:
        r = await c.send(p.request())
    assert r.status_code == 200
    (req,) = w.server.requests
    sur = next(iter(p.mapping.back))
    assert req["target"] == f"/key/Leafi/{sur}%20read%203%20pages"


async def test_a_guard_denial_is_a_403_and_not_retried(world):
    w = world
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    netguard.configure(netguard.Policy(mode="enforce", no_network=True, gateway_ports=frozenset({w.server.port})))
    async with w.egress.client("fake") as c:
        r = await c.send(p.request())
    assert r.status_code == 403 and "LEAFI_NO_NETWORK" in r.json()["refused"]
    assert w.server.requests == []


async def test_the_grant_ends_with_the_response(world):
    w = world
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco)
    async with w.egress.client("fake") as c:
        r = await c.send(p.request())
        await r.aread()
    assert netguard.live_grants() == []
    with pytest.raises(httpx2.ConnectError) as e:  # nothing outside egress reaches the gateway port
        async with httpx2.AsyncClient() as raw:
            await raw.get(f"http://127.0.0.1:{w.server.port}/")
    assert eg._denial(e.value) is not None
    assert len(w.server.requests) == 1


async def test_an_env_privacy_change_while_running_refuses_study_egress(world, tmp_path):
    w = world
    env = tmp_path / ".env"
    env.write_text("CLOUD_PARENT_TEXT=false\n", encoding="utf-8")
    e = eg.Egress(w.settings, registry=w.egress.registry, env_file=env)
    try:
        p = e.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")), learner_id=w.rocco)
        env.write_text("CLOUD_PARENT_TEXT=true\n", encoding="utf-8")
        async with e.client("fake") as c:
            r = await c.send(p.request())
        assert r.status_code == 403 and "household privacy" in r.json()["refused"]
        with pytest.raises(eg.Refused, match="restart"):
            e.prepare("fake", "generate", Outgoing(json={}), learner_id=w.rocco)
        e.prepare("fake", dests.OPS, Outgoing(json={"alert": "camera down"}))  # ops is not learner text
    finally:
        e.close()


def test_a_token_that_expires_unclaimed_closes_its_row(world):
    w = world
    w.egress.prepare("fake", "generate", Outgoing(json={}), learner_id=w.rocco, ttl_s=0)
    w.egress.prepare("fake", "generate", Outgoing(json={}), learner_id=w.rocco)
    assert [r[3] for r in _log(w)] == ["failed", "sending"]


def test_recovery_marks_a_dead_processes_attempts_unknown(world):
    w = world
    w.store.execute("INSERT INTO egress_log(destination, purpose, learner_id, payload_size, body_hmac, status, "
                    "transmitted_attempts, owner, created_at, updated_at) VALUES('fake', 'generate', ?, 1, 'h', "
                    "'sending', 1, '999999:1', 't', 't')", (w.rocco,))
    assert w.egress.recover() == 1
    assert _log(w)[-1][3:] == ("unknown", 1)
