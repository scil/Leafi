"""ADR-0016 alerts: the fixed catalog, the outbox and its one deliverer."""

from __future__ import annotations

import httpx
import pytest

from leafi.core import alerts
from leafi.core.storage import Store
from leafi.devices.notifiers import NotifierDevice
from leafi.ops.alerts import deliver


class FakeToast:
    def __init__(self, fail: bool = False) -> None:
        self.shown: list[str] = []
        self.fail = fail

    async def __call__(self, text: str) -> None:
        self.shown.append(text)
        if self.fail:
            raise RuntimeError("toast failed")


class FakeTelegram:
    can_send = True

    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[str] = []
        self.fail_times = fail_times

    async def send(self, text: str) -> None:
        if self.fail_times:
            self.fail_times -= 1
            raise httpx.ConnectError("down")
        self.sent.append(text)


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def test_render_maps_codes_to_fixed_sentences_and_never_echoes_input():
    gave_up = alerts.render("camera", "down", "restart_gave_up")
    assert "restarted repeatedly" in gave_up and gave_up == alerts.render("camera", "down", "restart_gave_up")
    assert alerts.render("study-mic", "event", "mic_lost") != alerts.UNKNOWN
    hostile = alerts.render("study-mic", "event", "Microphone (DJI Mic Mini) — Alice")
    assert hostile == alerts.UNKNOWN
    assert alerts.render("camera; rm -rf", "down", "restart_gave_up") == alerts.UNKNOWN
    assert alerts.render("camera", "sideways", "restart_gave_up") == alerts.UNKNOWN


def test_every_supervised_service_has_a_gave_up_and_a_recovered_sentence():
    for svc in ("camera", "habit-agent", "docker", "frigate", "mosquitto", "ollama"):
        assert alerts.render(svc, "down", "restart_gave_up") != alerts.UNKNOWN, svc
        assert alerts.render(svc, "up", "recovered") != alerts.UNKNOWN, svc
    assert alerts.render("supervisor", "down", "repeated_exits") != alerts.UNKNOWN


def test_every_catalog_sentence_is_plain_text_without_placeholders():
    for (key, state, reason), text in alerts.CATALOG.items():
        assert key in alerts.KEYS and state in alerts.STATES
        assert "{" not in text and "\n" not in text and len(text) < 300, (key, reason)


async def test_deliver_sends_rows_in_order_with_one_toast_each(store):
    alerts.insert(store, "camera", "down", "restart_gave_up")
    alerts.insert(store, "camera", "up", "recovered")
    toast, tg = FakeToast(), FakeTelegram()
    assert await deliver(store, toast, tg, now=Clock()) == 2
    assert tg.sent == [alerts.render("camera", "down", "restart_gave_up"), alerts.render("camera", "up", "recovered")]
    assert toast.shown == tg.sent
    assert await deliver(store, toast, tg, now=Clock()) == 0  # nothing left


async def test_a_failed_send_holds_later_rows_and_retries_without_a_second_toast(store):
    alerts.insert(store, "camera", "down", "restart_gave_up")
    alerts.insert(store, "camera", "up", "recovered")
    toast, tg, clock = FakeToast(), FakeTelegram(fail_times=1), Clock()
    assert await deliver(store, toast, tg, now=clock) == 0
    assert tg.sent == []  # the up row waits behind the unsent down row on Telegram …
    assert len(toast.shown) == 2  # … but both toasts went out at once: local notice never waits for Telegram
    assert await deliver(store, toast, tg, now=clock) == 0  # not due yet: next_try_at is 30 s away
    clock.t += 31
    assert await deliver(store, toast, tg, now=clock) == 2
    assert tg.sent[0] == alerts.render("camera", "down", "restart_gave_up")  # a recovery never precedes its outage
    assert len(toast.shown) == 2  # no toast repeated
    row = store.one("SELECT attempts FROM alert_outbox WHERE id = 1")
    assert row["attempts"] == 1


async def test_without_telegram_a_row_is_done_once_its_toast_is_shown(store):
    alerts.insert(store, "study-lease", "event", "lease_lost")
    toast = FakeToast()
    assert await deliver(store, toast, None, now=Clock()) == 1
    assert len(toast.shown) == 1


async def test_bark_only_notifier_does_not_hold_alerts_forever(store):
    alerts.insert(store, "study-mic", "event", "mic_lost")
    bark_only = NotifierDevice(options={"bark_url": "https://api.day.app/x"})
    assert await deliver(store, FakeToast(), bark_only, now=Clock()) == 1


async def test_a_failing_toast_does_not_block_telegram(store):
    alerts.insert(store, "study-mic", "event", "mic_lost")
    toast, tg = FakeToast(fail=True), FakeTelegram()
    assert await deliver(store, toast, tg, now=Clock()) == 1
    assert tg.sent == [alerts.render("study-mic", "event", "mic_lost")]


def _notifier(handler) -> NotifierDevice:
    return NotifierDevice(options={"telegram_bot_token": "t", "telegram_chat_id": "c",
                                   "transport": httpx.MockTransport(handler)})


async def test_notifier_send_raises_on_a_non_2xx_reply_and_succeeds_on_200():
    with pytest.raises(httpx.HTTPStatusError):
        await _notifier(lambda req: httpx.Response(502)).send("x")
    seen = []

    def ok(req):
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    await _notifier(ok).send("hello")
    assert seen[0].url.host == "api.telegram.org" and b"hello" in seen[0].content
