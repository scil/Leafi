"""Configuration checks, heartbeat and dashboard pushes (ADR-0016).

Each check reads facts from Windows (task scheduler, netsh, powercfg, registry, files) and applies a pure rule;
the rules are the tested part. A failing check raises one `check-<name>` alert through its latch and the first
passing run afterwards raises the `up` row. Checks never repair anything: changing Windows, Docker or `.env`
settings is the owner's decision. A check that cannot run (a tool missing, a timeout) changes nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from leafi.core import alerts, envfile
from leafi.core.storage import Store, now_iso

log = logging.getLogger("leafi.checks")

# Every port Leafi or its containers bind on the host (go2rtc API/RTSP, Frigate UI/RTSP/WebRTC/go2rtc, MQTT,
# the supervisor's rearm listener, Gatus).
PORTS = (2984, 2554, 15000, 8554, 8555, 1984, 18830, 18771, 18080)
POWERSHELL_APP = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


# ---------------------------------------------------------------- pure rules (tested)

def parse_excluded_ranges(netsh_output: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in re.findall(r"^\s*(\d+)\s+(\d+)", netsh_output, re.MULTILINE)]


def ports_blocked(ports, ranges: list[tuple[int, int]]) -> list[int]:
    return [p for p in ports if any(a <= p <= b for a, b in ranges)]


def ac_index(powercfg_output: str) -> int | None:
    m = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", powercfg_output)
    return int(m.group(1), 16) if m else None


def hours_cover(start: int, end: int, need_from: int, need_to: int) -> bool:
    """Windows Update active hours [start, end) (may wrap midnight) contain every hour in [need_from, need_to)."""
    def inside(h: int) -> bool:
        return start <= h < end if start <= end else (h >= start or h < end)
    return all(inside(h) for h in range(need_from, need_to))


def toasts_enabled(global_value: int | None, app_value: int | None) -> bool:
    """Absent registry values mean the Windows default (on); only an explicit 0 disables."""
    return global_value != 0 and app_value != 0


def task_ok(info: dict | None) -> bool:
    if not info or info.get("State") == "Disabled":
        return False
    return ("MSFT_TaskLogonTrigger" in (info.get("Triggers") or []) and bool(info.get("Repeats"))
            and info.get("MultipleInstances") == "IgnoreNew" and info.get("ExecutionTimeLimit") in ("PT0S", ""))


def docker_autostart(path: Path) -> bool:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("AutoStart") is True
    except (OSError, ValueError):
        return False


def sha256_matches(path: Path, expected: str) -> bool:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected.strip().lower()
    except OSError:
        return False


CHANNELS = ("telegram", "heartbeat")  # what REQUIRED_CHANNELS may list (the settings page offers these)


def parse_active_hours(text: str) -> tuple[int, int]:
    """`ACTIVE_HOURS` "7-21" -> (7, 21); raises ValueError. Pure: also the settings page's validator."""
    need_from, _, need_to = text.partition("-")
    return int(need_from), int(need_to)


def channel_ok(settings, channel: str) -> bool:
    required = {c.strip() for c in settings.required_channels.split(",") if c.strip()}
    if channel not in required:
        return True
    if channel == "telegram":
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)
    return bool(settings.heartbeat_url)


# ---------------------------------------------------------------- reading facts from Windows

def _out(cmd: list[str], limit_s: float = 30) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=limit_s,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


TASK_QUERY = (
    "$t = Get-ScheduledTask -TaskName 'leafi-supervisor' -ErrorAction SilentlyContinue; "
    "if (-not $t) { 'null' } else { [pscustomobject]@{ State = \"$($t.State)\"; "
    "Triggers = @($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }); "
    "Repeats = [bool](@($t.Triggers | Where-Object { $_.Repetition.Interval }).Count); "
    "MultipleInstances = \"$($t.Settings.MultipleInstances)\"; "
    "ExecutionTimeLimit = \"$($t.Settings.ExecutionTimeLimit)\" } | ConvertTo-Json -Compress }")


def _task_info() -> dict | None:
    return json.loads(_out(["powershell.exe", "-NoProfile", "-Command", TASK_QUERY]).strip() or "null")


def _reg(root: str, key: str, name: str) -> int | None:
    import winreg

    hive = winreg.HKEY_CURRENT_USER if root == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(hive, key) as k:
            return int(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


def _power_ok() -> bool:
    values = [ac_index(_out(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", s]))
              for s in ("STANDBYIDLE", "HIBERNATEIDLE")]
    if None in values:
        raise OSError("powercfg gave no AC value")
    return all(v == 0 for v in values)


def _models_ok(settings) -> bool:
    from leafi import doctor

    return all(state not in ("missing", "error") for _, _, state, _ in doctor.rows(settings))


def _devices_ok(settings) -> bool:
    from leafi.core.config import env_lookup
    from leafi.core.hub import DevicesConfigError, load_devices_config

    try:
        load_devices_config(settings.devices_file, lambda n: env_lookup(n, settings))
    except (DevicesConfigError, OSError, ValueError):
        return False
    return True


# ---------------------------------------------------------------- the checks and their latches

@dataclass
class Check:
    name: str
    run: Callable[[], Awaitable[bool]]


def build(settings) -> list[Check]:
    def threaded(fn: Callable[[], bool]) -> Callable[[], Awaitable[bool]]:
        async def run() -> bool:
            return await asyncio.to_thread(fn)
        return run

    def active_hours() -> bool:
        key = r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
        start, end = _reg("HKLM", key, "ActiveHoursStart"), _reg("HKLM", key, "ActiveHoursEnd")
        return start is not None and end is not None and hours_cover(start, end, *parse_active_hours(settings.active_hours))

    return [
        Check("task", threaded(lambda: task_ok(_task_info()))),
        Check("docker-autostart", threaded(lambda: docker_autostart(settings.docker_settings_file))),
        Check("go2rtc-patched", threaded(lambda: sha256_matches(Path(settings.go2rtc_exe), settings.go2rtc_sha256))),
        Check("ports", threaded(lambda: not ports_blocked(PORTS, parse_excluded_ranges(
            _out(["netsh", "int", "ipv4", "show", "excludedportrange", "protocol=tcp"])))))
        ,
        Check("power", threaded(_power_ok)),
        Check("toasts", threaded(lambda: toasts_enabled(
            _reg("HKCU", r"Software\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled"),
            _reg("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\\" + POWERSHELL_APP,
                 "Enabled")))),
        Check("active-hours", threaded(active_hours)),
        Check("disk", threaded(lambda: shutil.disk_usage(Path(settings.data_dir).resolve().anchor).free
                               >= settings.min_free_gb * 1e9)),
        Check("models", threaded(lambda: _models_ok(settings))),
        Check("household-terms", threaded(lambda: _schools_answered(settings))),
        Check("telegram", threaded(lambda: channel_ok(settings, "telegram"))),
        Check("heartbeat", threaded(lambda: channel_ok(settings, "heartbeat"))),
        Check("devices", threaded(lambda: _devices_ok(settings))),
        Check("supervision-timing", threaded(lambda: timing_ok(settings))),
        Check("env-file", threaded(lambda: not envfile.health(Path(".env"), Path(settings.data_dir)))),
    ]


def timing_ok(settings) -> bool:
    """The timing settings satisfy every invariant and the dashboard heartbeat outlasts one poll (ADR-0016)."""
    from leafi.ops import timing

    t, problems = timing.resolve(settings)
    services = [s.strip() for s in settings.supervise.split(",") if s.strip()]
    gatus_cfg = Path(settings.devices_file).parent / "gatus" / "config.yaml"
    return not problems and timing.heartbeat_ok(timing.gatus_heartbeat_s(gatus_cfg), t, services)


def _schools_answered(settings) -> bool:
    """Every enrolled learner has a school answer (ADR-0018 §3); read-only, like `leafi doctor`'s line."""
    import json
    import sqlite3

    if not Path(settings.db_path).exists():
        return True
    c = sqlite3.connect(f"file:{Path(settings.db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT settings FROM learners WHERE kind='learner' AND forgetting=0").fetchall()
    finally:
        c.close()
    return all(json.loads(s or "{}").get("privacy.school") is not None for (s,) in rows)


NAMES = ("task", "docker-autostart", "go2rtc-patched", "ports", "power", "toasts", "active-hours", "disk",
         "models", "household-terms", "telegram", "heartbeat", "devices", "supervision-timing", "env-file")


class CheckRunner:
    """Runs every check; one latch per check (a `service_state` row named `check-<name>`)."""

    def __init__(self, store: Store, items: list[Check]) -> None:
        self.store, self.items = store, items
        for c in items:
            if store.one("SELECT service FROM service_state WHERE service = ?", (self._key(c),)) is None:
                store.insert("service_state", service=self._key(c), updated_at=now_iso())

    @staticmethod
    def _key(c: Check) -> str:
        return f"check-{c.name}"

    async def run_all(self) -> dict[str, bool | None]:
        results: dict[str, bool | None] = {}
        for c in self.items:
            try:
                ok = bool(await asyncio.wait_for(c.run(), 120))
            except Exception:  # noqa: BLE001 - a check that cannot run changes nothing
                log.warning("check %s could not run", c.name, exc_info=True)
                results[c.name] = None
                continue
            results[c.name] = ok
            self._latch(c, ok)
        return results

    def _latch(self, c: Check, ok: bool) -> None:
        key = self._key(c)
        latch = self.store.one("SELECT latch FROM service_state WHERE service = ?", (key,))["latch"]
        want = "up" if ok else "down"
        if latch == want:
            return
        with self.store.transaction():
            self.store.execute("UPDATE service_state SET latch = ?, updated_at = ? WHERE service = ?",
                               (want, now_iso(), key))
            alerts.insert(self.store, key, want, "recovered" if ok else "failed")
        (log.info if ok else log.warning)("check %s %s", c.name, "passes again" if ok else "FAILS")


# ---------------------------------------------------------------- heartbeat and dashboard

async def heartbeat(egress, url: str) -> None:
    """Dead man's switch: a bodyless GET through `leafi.privacy.egress` (purpose `ops`); Healthchecks.io alerts
    the owner when these stop."""
    if not url:
        return
    from urllib.parse import urlsplit

    from leafi.privacy.destinations import OPS
    from leafi.privacy.egress import Outgoing, Refused

    try:
        p = egress.prepare("healthchecks", OPS, Outgoing(method="GET", path=urlsplit(url).path or "/"))
        async with egress.client("healthchecks", timeout=5) as c:
            await c.send(p.request())
    except (httpx.HTTPError, Refused) as e:
        log.debug("heartbeat failed: %s", type(e).__name__)


async def push(client: httpx.AsyncClient, base: str, token: str, group: str, name: str, ok: bool,
               reason: str) -> None:
    """One result to the read-only Gatus dashboard; a failure is dropped (the outbox is the record)."""
    if not token:
        return
    params = {"success": "true" if ok else "false"}
    if not ok and reason:
        params["error"] = reason
    try:
        await client.post(f"{base.rstrip('/')}/api/v1/endpoints/{group}_{name}/external", params=params,
                          headers={"Authorization": f"Bearer {token}"}, timeout=3)
    except httpx.HTTPError as e:
        log.debug("dashboard push %s_%s failed: %s", group, name, type(e).__name__)
