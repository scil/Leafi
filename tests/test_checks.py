"""ADR-0016 configuration checks: pure pass/fail rules over facts read from Windows, and their alert latches."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from leafi.core import alerts
from leafi.core.storage import Store
from leafi.ops import checks

NETSH = """
Protocol tcp Port Exclusion Ranges

Start Port    End Port
----------    --------
      1848        1947
     50000       50059     *
     15000       15099

* - Administered port exclusions.
"""


def test_excluded_port_ranges_are_parsed_and_matched():
    ranges = checks.parse_excluded_ranges(NETSH)
    assert (1848, 1947) in ranges and (50000, 50059) in ranges
    assert checks.ports_blocked([2984, 15000, 18830], ranges) == [15000]
    assert checks.ports_blocked([2984, 18830], ranges) == []


POWER_NEVER = "    Current AC Power Setting Index: 0x00000000\n    Current DC Power Setting Index: 0x00000258\n"
POWER_30MIN = "    Current AC Power Setting Index: 0x00000708\n"


def test_power_check_reads_the_ac_value_only():
    assert checks.ac_index(POWER_NEVER) == 0
    assert checks.ac_index(POWER_30MIN) == 1800
    assert checks.ac_index("garbage") is None


@pytest.mark.parametrize("start, end, ok", [
    (7, 1, True),     # 07:00 → 01:00 (wraps midnight) covers 7–21
    (6, 23, True),
    (8, 17, False),   # updates may reboot at 18:00
    (22, 6, False),
    (7, 21, True),
])
def test_active_hours_must_cover_the_household_day(start, end, ok):
    assert checks.hours_cover(start, end, 7, 21) is ok


@pytest.mark.parametrize("global_on, app_on, ok", [(None, None, True), (1, None, True), (0, None, False),
                                                    (None, 0, False)])
def test_toasts_fail_only_when_explicitly_disabled(global_on, app_on, ok):
    assert checks.toasts_enabled(global_on, app_on) is ok


TASK_OK = {"State": "Ready", "Triggers": ["MSFT_TaskLogonTrigger", "MSFT_TaskTimeTrigger"], "Repeats": True,
           "MultipleInstances": "IgnoreNew", "ExecutionTimeLimit": "PT0S"}


@pytest.mark.parametrize("info, ok", [
    (TASK_OK, True),
    ({**TASK_OK, "State": "Running"}, True),
    (None, False),                                        # not installed
    ({**TASK_OK, "State": "Disabled"}, False),
    ({**TASK_OK, "Triggers": ["MSFT_TaskLogonTrigger"], "Repeats": False}, False),  # no relaunch trigger
    ({**TASK_OK, "MultipleInstances": "Parallel"}, False),
    ({**TASK_OK, "ExecutionTimeLimit": "PT72H"}, False),
])
def test_task_check(info, ok):
    assert checks.task_ok(info) is ok


def test_docker_autostart_reads_settings_store(tmp_path):
    f = tmp_path / "settings-store.json"
    f.write_text(json.dumps({"AutoStart": True}), encoding="utf-8")
    assert checks.docker_autostart(f) is True
    f.write_text(json.dumps({"AutoStart": False}), encoding="utf-8")
    assert checks.docker_autostart(f) is False
    assert checks.docker_autostart(tmp_path / "missing.json") is False


def test_go2rtc_hash_must_match_the_patched_build(tmp_path):
    exe = tmp_path / "go2rtc.exe"
    exe.write_bytes(b"patched build")
    good = hashlib.sha256(b"patched build").hexdigest()
    assert checks.sha256_matches(exe, good.upper()) is True
    assert checks.sha256_matches(exe, "0" * 64) is False
    assert checks.sha256_matches(tmp_path / "absent.exe", good) is False


def test_channel_checks_follow_required_channels(settings):
    settings.required_channels = "telegram,heartbeat"
    settings.telegram_bot_token = settings.telegram_chat_id = settings.heartbeat_url = ""
    assert checks.channel_ok(settings, "telegram") is False
    assert checks.channel_ok(settings, "heartbeat") is False
    settings.required_channels = ""  # toast-only is a supported choice
    assert checks.channel_ok(settings, "telegram") is True and checks.channel_ok(settings, "heartbeat") is True


def test_every_check_has_a_down_and_up_sentence():
    for name in checks.NAMES:
        assert alerts.render(f"check-{name}", "down", "failed") != alerts.UNKNOWN, name
        assert alerts.render(f"check-{name}", "up", "recovered") != alerts.UNKNOWN, name


async def test_a_failing_check_alerts_once_and_once_more_when_it_passes(tmp_path):
    store = Store(tmp_path / "leafi.db")
    state = {"ok": False}

    async def flaky() -> bool:
        return state["ok"]

    runner = checks.CheckRunner(store, [checks.Check("power", flaky)])
    for _ in range(3):
        await runner.run_all()
    state["ok"] = True
    await runner.run_all()
    await runner.run_all()
    rows = [tuple(r) for r in store.all("SELECT key, state, reason FROM alert_outbox ORDER BY id")]
    assert rows == [("check-power", "down", "failed"), ("check-power", "up", "recovered")]


async def test_a_check_that_raises_changes_nothing(tmp_path):
    store = Store(tmp_path / "leafi.db")

    async def broken() -> bool:
        raise OSError("powercfg missing")

    runner = checks.CheckRunner(store, [checks.Check("power", broken)])
    results = await runner.run_all()
    assert results == {"power": None}
    assert store.one("SELECT COUNT(*) AS n FROM alert_outbox")["n"] == 0


# ---------------------------------------------------------------- heartbeat and dashboard pushes


async def test_heartbeat_is_a_bodyless_get_and_skipped_without_a_url(settings):
    from tests.egress_helpers import mock_egress

    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200)

    url = "https://hc-ping.com/1f2e3d4c-0000-4000-8000-123456789abc"
    settings.heartbeat_url = url
    e = mock_egress(settings, handler)
    await checks.heartbeat(e, "")
    assert seen == []
    await checks.heartbeat(e, url)
    assert seen[0].method == "GET" and seen[0].content == b"" and str(seen[0].url) == url


async def test_dashboard_push_uses_the_external_endpoint_api_and_never_raises():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await checks.push(c, "http://127.0.0.1:18080", "tok", "services", "camera", False, "BAD")
        await checks.push(c, "http://127.0.0.1:18080", "", "services", "camera", True, "")  # no token: no push
    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/api/v1/endpoints/services_camera/external"
    assert req.url.params["success"] == "false" and req.url.params["error"] == "BAD"
    assert req.headers["authorization"] == "Bearer tok"

    def down(req):
        raise httpx.ConnectError("gatus down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as c:
        await checks.push(c, "http://127.0.0.1:18080", "tok", "checks", "power", True, "")  # dropped, no raise


def test_gatus_config_declares_every_service_and_check_and_no_alerting():
    import yaml

    from tests.test_architecture import ROOT

    cfg = yaml.safe_load((ROOT / "config" / "gatus" / "config.yaml").read_text(encoding="utf-8"))
    assert "alerting" not in cfg  # Gatus sends nothing
    # it probes only itself (Gatus 5.37 requires one active endpoint) and attaches no alert to anything
    assert [e["url"] for e in cfg["endpoints"]] == ["http://localhost:8080/health"]
    assert all("alerts" not in e for e in cfg["endpoints"])
    names = {(e["group"], e["name"]) for e in cfg["external-endpoints"]}
    assert {("services", s) for s in alerts.SERVICES} <= names
    assert {("checks", c) for c in checks.NAMES} <= names
    assert ("leafi", "supervisor") in names
    for e in cfg["external-endpoints"]:
        assert "alerts" not in e
