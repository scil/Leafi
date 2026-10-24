"""Operational alerts (ADR-0016): the fixed catalog, `render()` and the outbox insert.

Every alert that leaves the PC is one sentence from `CATALOG`, chosen by codes. Writers pass codes only, never
exception text or device names (a `ListenerLost` message names the microphone), so nothing a writer could fill
reaches Telegram; an unknown code renders as `UNKNOWN`. `leafi/ops/alerts.py::deliver` is the only sender.
"""

from __future__ import annotations

from leafi.core.storage import Store, now_iso

STATES = frozenset({"down", "up", "event"})

_GAVE_UP = {
    "camera": "Leafi camera: go2rtc was restarted repeatedly and the camera still sends no video. Restarts are paused; "
              "close the Mi Home app if it is open, check the camera, then press the go2rtc restart button.",
    "habit-agent": "Leafi habit coach kept failing; it was restarted repeatedly. Restarts are paused; see data/logs "
                   "on the PC.",
    "docker": "Docker Desktop is not answering after repeated restarts, so Frigate and MQTT are down. Restarts are paused; "
              "open Docker Desktop on the PC.",
    "frigate": "Frigate is not answering after repeated restarts. Restarts are paused; see the health check on the PC.",
    "mosquitto": "The MQTT broker is not answering after repeated restarts. Restarts are paused; see the health check on "
                 "the PC.",
    "ollama": "Ollama is not answering after repeated restarts. Restarts are paused; see data/logs on the PC.",
    "gatus": "The Leafi dashboard (Gatus) is not answering after repeated restarts. Alerts still work; see the health "
             "check on the PC.",
}
_NAMES = {"camera": "Leafi camera: video is", "habit-agent": "Leafi habit coach is", "docker": "Docker Desktop is",
          "frigate": "Frigate is", "mosquitto": "The MQTT broker is", "ollama": "Ollama is",
          "gatus": "The Leafi dashboard is"}
SERVICES = frozenset(_GAVE_UP)

# Configuration checks (ADR-0016): what is wrong and what the owner should do; nothing is repaired automatically.
_CHECK_FAILED = {
    "task": "The leafi-supervisor logon task is missing or misconfigured. Run scripts\\win\\install-tasks.ps1.",
    "docker-autostart": "Docker Desktop is not set to start at sign-in. Turn on 'Start Docker Desktop when you "
                        "sign in' in its settings.",
    "go2rtc-patched": "tools\\go2rtc\\go2rtc.exe is not the patched build Leafi expects. Read "
                      "tools/go2rtc/PATCHES.md before replacing it; update GO2RTC_SHA256 after a patched rebuild.",
    "ports": "Windows now reserves a port Leafi needs (go2rtc, Frigate, MQTT, the supervisor or the dashboard). "
             "Run the health check; a reboot or a port change in .env fixes it.",
    "power": "The PC is set to sleep or hibernate on mains power, which stops every Leafi service. Set both to "
             "Never in the power settings.",
    "toasts": "Windows notifications are turned off for PowerShell, so Leafi's pop-up alerts are invisible. Turn "
              "them on in Settings > Notifications.",
    "active-hours": "Windows Update active hours do not cover the household day, so an update may reboot the PC "
                    "while it is needed. Widen them in Windows Update settings.",
    "disk": "The data drive is almost full. Free some space on the PC.",
    "models": "A Leafi model is missing or broken. Run python -m leafi doctor on the PC.",
    "household-terms": "A learner has no school answer, so their school's name cannot be replaced if it appears "
                       "in what is sent. Run python -m leafi privacy schools on the PC.",
    "telegram": "Telegram alerts are not configured (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in .env), so alerts "
                "only appear on the PC.",
    "heartbeat": "The heartbeat is not configured (HEARTBEAT_URL in .env), so nobody is told when the PC itself "
                 "stops.",
    "devices": "config/devices.yml no longer parses. Run python -m leafi devices on the PC.",
    "supervision-timing": "Some supervision timing settings conflict, so the supervisor uses their defaults. Run "
                          "python -m leafi timing on the PC to see which and why.",
    "env-file": ".env is missing, not in canonical form, or a save left recovery files (data/env-recovery*.json, "
                ".env.*.side). Open the settings page on the PC; it lists what to fix.",
}

CATALOG: dict[tuple[str, str, str], str] = {
    **{(s, "down", "restart_gave_up"): text for s, text in _GAVE_UP.items()},
    **{(s, "up", "recovered"): f"{_NAMES[s]} back and has been steady since." for s in SERVICES},
    **{(f"check-{c}", "down", "failed"): f"Leafi check: {text}" for c, text in _CHECK_FAILED.items()},
    **{(f"check-{c}", "up", "recovered"): f"Leafi check '{c}' passes again." for c in _CHECK_FAILED},
    ("study-mic", "event", "mic_lost"):
        "Leafi reading session: the microphone stopped. The session continued on the keyboard or stopped; "
        "check the headset.",
    ("study-lease", "event", "lease_lost"):
        "Leafi reading session: another Leafi took over the speaker, so the session stopped. The reading is saved.",
    ("supervisor", "down", "repeated_exits"):
        "Leafi supervisor keeps crashing; no service is being watched. See data/logs on the PC.",
}
KEYS = frozenset(k for k, _, _ in CATALOG)
UNKNOWN = "Leafi raised an alert it could not describe. Run the health check on the PC."


def render(key: str, state: str, reason: str) -> str:
    """The one renderer: codes in, a fixed catalog sentence out."""
    return CATALOG.get((key, state, reason), UNKNOWN)


def insert(store: Store, key: str, state: str, reason: str) -> int:
    """Queue an alert; a local write, never a network call. An unknown code is kept as-is and renders as
    UNKNOWN, so a caller's mistake still reaches the owner without leaking its text."""
    if state not in STATES:
        state = "event"
    return store.insert("alert_outbox", key=str(key)[:64], state=state, reason=str(reason)[:64],
                        created_at=now_iso())
