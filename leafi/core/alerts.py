"""Operational alerts (ADR-0016): the fixed catalog, `render()` and the outbox insert.

Every alert that leaves the PC is one sentence from `CATALOG`, chosen by codes. Writers pass codes only, never
exception text or device names (a `ListenerLost` message names the microphone), so nothing a writer could fill
reaches Telegram; an unknown code renders as `UNKNOWN`. `leafi/ops/alerts.py::deliver` is the only sender.
"""

from __future__ import annotations

from leafi.core.storage import Store, now_iso

STATES = frozenset({"down", "up", "event"})

_GAVE_UP = {
    "camera": "Leafi camera: go2rtc was restarted 3 times and the camera still sends no video. Restarts are paused; "
              "close the Mi Home app if it is open, check the camera, then press the go2rtc restart button.",
    "habit-agent": "Leafi habit coach kept failing; it was restarted 3 times. Restarts are paused; see data/logs "
                   "on the PC.",
    "docker": "Docker Desktop is not answering after 3 restarts, so Frigate and MQTT are down. Restarts are paused; "
              "open Docker Desktop on the PC.",
    "frigate": "Frigate is not answering after 3 restarts. Restarts are paused; see the health check on the PC.",
    "mosquitto": "The MQTT broker is not answering after 3 restarts. Restarts are paused; see the health check on "
                 "the PC.",
    "ollama": "Ollama is not answering after 3 restarts. Restarts are paused; see data/logs on the PC.",
}
_NAMES = {"camera": "Leafi camera: video is", "habit-agent": "Leafi habit coach is", "docker": "Docker Desktop is",
          "frigate": "Frigate is", "mosquitto": "The MQTT broker is", "ollama": "Ollama is"}
SERVICES = frozenset(_GAVE_UP)

CATALOG: dict[tuple[str, str, str], str] = {
    **{(s, "down", "restart_gave_up"): text for s, text in _GAVE_UP.items()},
    **{(s, "up", "recovered"): f"{_NAMES[s]} back and has been steady for 10 minutes." for s in SERVICES},
    ("study-mic", "event", "mic_lost"):
        "Leafi reading session: the microphone stopped. The session continued on the keyboard or stopped; "
        "check the headset.",
    ("study-lease", "event", "lease_lost"):
        "Leafi reading session: another Leafi took over the speaker, so the session stopped. The reading is saved.",
    ("supervisor", "down", "repeated_exits"):
        "Leafi supervisor crashed 3 times in 30 minutes; no service is being watched. See data/logs on the PC.",
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
