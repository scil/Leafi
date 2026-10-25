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


async def test_text_is_redacted_by_content_and_never_refused_for_its_source(world):
    """ADR-0021 E1 (owner 2026-10-24): no text is refused for where it came from — a learner with `cloud.text` off,
    a guest, text naming no source learner, parent text with CLOUD_PARENT_TEXT off — it leaves redacted."""
    w = world
    leo = learner_store.create(w.store, "Leo")
    body = {"messages": [{"role": "user", "content": Text("Leo here", "learner", (leo,))}]}
    sent = w.egress.prepare("fake", "generate", Outgoing(json=body), learner_id=leo)
    assert b"Leo" not in sent.body  # no school answer, still pseudonymised
    privacy.set_school(w.store, leo, None)
    privacy.write(w.store, leo, "cloud.text", False)
    sent = w.egress.prepare("fake", "generate", Outgoing(json=body), learner_id=leo)
    assert b"here" in sent.body and b"Leo" not in sent.body  # sent, redacted
    guest = learner_store.create(w.store, "Guest", kind="guest")  # as guests.start_guest stores every guest
    sent = w.egress.prepare("fake", "generate", Outgoing(json={"t": Text("me and Leo", "learner", (guest,))}),
                            learner_id=guest)
    assert b"me and" in sent.body and b"Leo" not in sent.body  # a guest's words leave too, listed names replaced
    w.egress.prepare("fake", "generate", Outgoing(json={"t": Text("x", "learner")}), learner_id=w.rocco)
    w.settings.cloud_parent_text = False
    w.egress.prepare("fake", "generate", Outgoing(json={"t": Text("x", "parent")}), learner_id=w.rocco)
    w.settings.local_models = "local:m1"
    local = w.egress.prepare("local", "generate", Outgoing(json={**body, "model": "m1"}), learner_id=leo,
                             model="m1")  # a local model may read it
    assert b"Leo here" in local.body


def _local_body(text: str, learner: int, model: str) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": Text(text, "learner", (learner,))}]}


async def test_a_model_bound_destination_is_local_only_for_a_listed_model(world):
    """M7 design D1: Ollama-like destinations are local only for a `backend:model` on LOCAL_MODELS that is not a
    cloud-hosted name, on a loopback host; otherwise their text is gated and pseudonymised like any cloud call."""
    w = world
    loc = w.egress.registry["local"]
    assert loc.model_bound and not w.egress.registry["fake"].model_bound
    w.settings.local_models = "local:m1, local:big-cloud, local:qwen3:cloud"
    assert dests.effective(loc, "m1", w.settings) == "local"
    for model in ("m2", "big-cloud", "qwen3:cloud", "m1:latest"):  # unlisted, cloud-hosted names, inexact
        assert dests.effective(loc, model, w.settings) == "cloud", model
    lan = dests.Destination("lan_ollama", "http", frozenset({"192.168.1.5"}), 11434, frozenset({"generate"}), "local")
    assert dests.effective(lan, "m1", w.settings) == "cloud"  # a LAN host is not "this machine" (S9)
    named = dests.Destination("named", "http", frozenset({"localhost"}), 11434, frozenset({"generate"}), "local")
    w.settings.local_models = "named:m1"
    assert dests.effective(named, "m1", w.settings) == "local"
    probe = dests.Destination("probe", "http", frozenset({"127.0.0.1"}), 11434, frozenset({dests.OPS}), "local")
    assert not probe.model_bound and dests.effective(probe, None, w.settings) == "local"  # ops: unchanged


async def test_an_unlisted_local_model_is_treated_as_cloud_and_redacted(world):
    w = world
    w.settings.local_models = "local:m1"
    sent = w.egress.prepare("local", "generate", Outgoing(json=_local_body("Rocco read it.", w.rocco, "m2")),
                            learner_id=w.rocco, model="m2")
    assert b"Rocco" not in sent.body  # treated as cloud: replaced by a surrogate
    leo = learner_store.create(w.store, "Leo")
    privacy.set_school(w.store, leo, None)
    privacy.write(w.store, leo, "cloud.text", False)
    sent = w.egress.prepare("local", "generate", Outgoing(json=_local_body("Leo here", leo, "m2")), learner_id=leo,
                            model="m2")
    assert b"Leo" not in sent.body  # ADR-0021: sent redacted, not refused
    kept = w.egress.prepare("local", "generate", Outgoing(json=_local_body("Leo here", leo, "m1")), learner_id=leo,
                            model="m1")
    assert b"Leo here" in kept.body  # listed: local, as LOCAL_MODELS allows


async def _send(w, dest: str, p) -> httpx2.Response:
    async with w.egress.client(dest) as c:
        return await c.send(p.request())


async def test_a_parent_origin_source_passes_admit_and_is_never_gated(world):
    """M7 design D2 / S1: source 0 marks parent origin in a mixed output. It never reaches the version snapshot
    as a 'learner 0' (that refused every such request at admit); since ADR-0021 no source gates a send."""
    from leafi.core.provenance import PARENT_SOURCE

    w = world
    mixed = {"model": "m1", "messages": [{"role": "user",
                                          "content": Text("Rocco likes rockets", "derived_from_learner",
                                                          (w.rocco, PARENT_SOURCE))}]}
    w.settings.local_models = "local:m1"
    p = w.egress.prepare("local", "generate", Outgoing(path="/v1/chat", json=mixed), learner_id=w.rocco, model="m1")
    assert (await _send(w, "local", p)).status_code == 200  # admitted: no "source learner 0 is gone"
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=mixed), learner_id=w.rocco)
    assert (await _send(w, "fake", p)).status_code == 200
    w.settings.cloud_parent_text = False
    w.egress.prepare("fake", "generate", Outgoing(json=mixed), learner_id=w.rocco)
    only_parent = {"t": Text("x", "derived_from_learner", (PARENT_SOURCE,))}
    w.egress.prepare("fake", "generate", Outgoing(json=only_parent), learner_id=w.rocco)
    assert _log(w)[:2] == [("local", "generate", w.rocco, "sent", 1), ("fake", "generate", w.rocco, "sent", 1)]


async def test_the_ollama_adapter_names_its_model_and_is_local_only_when_listed(world):
    """The v1 Ollama adapter (M7a bridge) passes its model; page text naming a learner reaches it as written only
    when `ollama:<model>` is on LOCAL_MODELS (M7 design D1), else with the surrogate."""
    from leafi.services.brain import BrainRequest, Intent
    from leafi.services.brain.ollama import OllamaBrain

    w = world
    w.egress.registry["ollama"] = dests.Destination("ollama", "http", frozenset({"127.0.0.1"}), w.server.port,
                                                    dests.BRAIN, "local")
    w.settings.brain_local_model = "m1"
    req = BrainRequest(Intent.EXPLAIN_SENTENCE, "Rocco went home.", learner_id=w.rocco)
    w.settings.local_models = "ollama:m1"
    await OllamaBrain(w.settings, egress=w.egress).run(req)
    w.settings.local_models = ""
    await OllamaBrain(w.settings, egress=w.egress).run(req)
    listed, unlisted = (r["body"] for r in w.server.requests)
    assert json.loads(listed)["model"] == "m1" and b"Rocco" in listed
    assert b"Rocco" not in unlisted


async def test_the_checked_model_must_be_the_one_sent(world):
    w = world
    w.settings.local_models = "local:m1"
    with pytest.raises(eg.Refused, match="names the model"):
        w.egress.prepare("local", "generate", Outgoing(json=_local_body("hi", w.rocco, "m1")), learner_id=w.rocco)
    with pytest.raises(eg.Refused, match="body names model 'm2'"):
        w.egress.prepare("local", "generate", Outgoing(json=_local_body("hi", w.rocco, "m2")), learner_id=w.rocco,
                         model="m1")
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco, model="claude-x")  # a cloud destination: the model is recorded
    assert w.egress.tokens.claim(p.token_id).model == "claude-x"


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


class _Ledger:
    """A caller's budget (M7 design D7): one unit per transmission; records what was charged."""

    def __init__(self, units: int) -> None:
        self.units, self.charged = units, []

    def can_cover(self, first: bool) -> bool:
        return self.units >= 1

    def charge(self, first: bool) -> None:
        self.units -= 1
        self.charged.append(first)


async def test_a_budget_that_cannot_cover_reserves_and_charges_nothing(world):
    w = world
    ledger = _Ledger(0)
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco, budget=ledger)
    r = await _send(w, "fake", p)
    assert r.status_code == 403 and "over budget" in r.text
    assert ledger.charged == [] and w.server.requests == [] and _log(w)[-1][3:] == ("failed", 0)


async def test_each_reserved_transmission_is_charged_once_including_the_retry(world):
    w = world
    w.server.replies += [(503, {"error": "x"}, {}), (200, _MESSAGE("ok"), {})]
    ledger = _Ledger(5)
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco, budget=ledger)
    assert p.attempt_id == w.store.one("SELECT MAX(id) FROM egress_log")[0]
    assert (await _send(w, "fake", p)).status_code == 200
    assert ledger.charged == [True, False] and _log(w)[-1][3:] == ("sent", 2)


async def test_a_busy_reservation_charges_once_and_a_change_during_the_wait_is_seen(world):
    import sqlite3

    w = world
    ledger = _Ledger(5)
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco, budget=ledger)
    blocker = sqlite3.connect(str(w.settings.db_path), isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")

    async def release():
        await asyncio.sleep(0.4)
        blocker.execute("COMMIT")

    task = asyncio.create_task(release())
    assert (await _send(w, "fake", p)).status_code == 200
    await task
    assert ledger.charged == [True]  # several busy attempts, one charge
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=_brain_body(w, "hi")),
                         learner_id=w.rocco, budget=ledger)
    # The blocker itself bumps the learner's privacy version inside its transaction: the change commits exactly
    # when the lock goes, so the attempt that finally gets the lock must see it (R3, round 5 #10).
    settings = json.loads(w.store.one("SELECT settings FROM learners WHERE id=?", (w.rocco,))[0])
    settings["privacy.version"] = int(settings.get("privacy.version", 0)) + 1
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("UPDATE learners SET settings=? WHERE id=?", (json.dumps(settings), w.rocco))
    task = asyncio.create_task(release())
    r = await _send(w, "fake", p)
    await task
    assert r.status_code == 403 and "privacy settings of learner" in r.json()["refused"]
    assert ledger.charged == [True] and len(w.server.requests) == 1  # nothing charged or sent for the stale one
    blocker.close()


async def test_the_detector_settles_off_at_once_and_never_loads_on_the_loop_in_a_session(world, monkeypatch):
    import threading

    from leafi.privacy import detector, runtime

    w = world
    assert w.egress.detector() is None and w.egress.detector_state == "off"  # no model here: nothing to load
    e = eg.Egress(w.settings, registry=w.egress.registry, env_file=None)
    gate = threading.Event()
    monkeypatch.setattr(detector, "state", lambda s: "on")
    monkeypatch.setattr(detector, "load", lambda s: gate.wait(5) and "DET")
    e.start_detector()
    assert e.detector_state == "loading"
    body = Outgoing(json={"m": Text("Rocco here", "learner", (w.rocco,))})
    with runtime.attributed(w.rocco), pytest.raises(eg.Refused, match="detector not ready"):
        e.prepare("fake", "generate", body, learner_id=w.rocco)
    with runtime.attributed(w.rocco), pytest.raises(eg.Refused, match="detector not ready"):  # any non-book text
        e.prepare("fake", "generate", Outgoing(json={"m": Text("a hint", "system")}), learner_id=w.rocco)
    with runtime.attributed(w.rocco):  # book text alone does not wait for the detector (ADR-0021 E3)
        e.prepare("fake", "generate", Outgoing(json={"m": Text("Rocco went home.", book=True)}), learner_id=w.rocco)
    gate.set()
    assert e.detector() == "DET" and e.detector_state == "ready"  # outside a session: waits for the load
    broken = eg.Egress(w.settings, registry=w.egress.registry, env_file=None)
    monkeypatch.setattr(detector, "load", lambda s: (_ for _ in ()).throw(OSError("bad model")))
    broken.start_detector()
    broken._det_done.wait(5)
    assert broken.detector_state == "failed" and broken.detector() is None  # list-only, like a missing model
    e.close()
    broken.close()


async def test_the_sdk_sends_the_decide_schema_exactly_as_prepared(world):
    """M7 design D6: `messages.create(**prepared.json)` with `output_config` and the real `decide` schema (nested
    $defs, anyOf, non-ASCII) is accepted by the mediator's body comparison and arrives unchanged."""
    from leafi.study.brain import schemas

    w = world
    body = {**_brain_body(w, "Rocco read “the fox” — twice."),
            "output_config": {"format": {"type": "json_schema", "schema": schemas.api_schema(schemas.Decision)},
                              "effort": "low"}}
    p = w.egress.prepare("fake", "generate", Outgoing(path="/v1/messages", json=body), learner_id=w.rocco)
    await _sdk(w).messages.create(**p.json, extra_headers={eg.TOKEN_HEADER: p.token_id})
    (req,) = w.server.requests
    assert json.loads(req["body"]) == p.json
