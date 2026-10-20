"""Habit track respects the study speech lease; parent snapshot is owner opt-in (ADR-0011)."""

from __future__ import annotations

import json
import os
import time

import agent.notify as notify
import agent.speaker as speaker
from leafi.core import lease


async def test_speaker_stays_silent_while_the_study_lease_is_held(tmp_path, monkeypatch):
    path = tmp_path / "leafi.lock"
    held = lease.acquire(path, ttl_s=60)
    monkeypatch.setattr(speaker, "LEASE_PATH", path)
    monkeypatch.setattr(speaker.settings, "mock", False)

    async def no_synth(text):
        raise AssertionError("must not synthesise while the lease is held")

    monkeypatch.setattr(speaker, "synth", no_synth)
    await speaker.say("time to brush")  # returns quietly
    held.release()
    assert not lease.is_held(path)


async def test_speaker_speaks_when_lease_is_stale_or_absent(tmp_path, monkeypatch):
    path = tmp_path / "leafi.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "token": "t", "expires": time.time() - 1}), encoding="utf-8")
    monkeypatch.setattr(speaker, "LEASE_PATH", path)
    monkeypatch.setattr(speaker.settings, "mock", True)
    called = []

    async def fake_synth(text):
        called.append(text)
        return tmp_path / "x.mp3"

    monkeypatch.setattr(speaker, "synth", fake_synth)
    await speaker.say("hello")
    assert called == ["hello"]


def test_lease_with_dead_pid_is_free_and_can_be_taken_over(tmp_path):
    path = tmp_path / "leafi.lock"
    path.write_text(json.dumps({"pid": 2 ** 30, "token": "t", "expires": time.time() + 60}), encoding="utf-8")
    assert not lease.is_held(path)
    taken = lease.acquire(path)
    assert lease.is_held(path)
    taken.release()


class _FakeClient:
    sent: list[tuple[str, dict]] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **k):
        _FakeClient.sent.append(("get", {"url": url}))

    async def post(self, url, **k):
        _FakeClient.sent.append(("post", {"url": url, **k}))


async def test_notify_attaches_snapshot_only_with_owner_opt_in(monkeypatch):
    monkeypatch.setattr(notify.settings, "mock", False)
    monkeypatch.setattr(notify.settings, "bark_url", "")
    monkeypatch.setattr(notify.settings, "telegram_bot_token", "T")
    monkeypatch.setattr(notify.settings, "telegram_chat_id", "C")
    monkeypatch.setattr(notify.httpx, "AsyncClient", _FakeClient)
    snaps = []

    async def fake_snapshot():
        snaps.append(1)
        return b"\xff\xd8jpeg"

    monkeypatch.setattr(notify, "snapshot", fake_snapshot)
    _FakeClient.sent = []
    monkeypatch.setattr(notify.settings, "notify_with_snapshot", False)
    await notify.send("brush", "done", with_snapshot=True)
    assert snaps == [] and _FakeClient.sent[0][1]["url"].endswith("/sendMessage")
    _FakeClient.sent = []
    monkeypatch.setattr(notify.settings, "notify_with_snapshot", True)
    await notify.send("brush", "done", with_snapshot=True)
    assert snaps == [1] and _FakeClient.sent[0][1]["url"].endswith("/sendPhoto")
