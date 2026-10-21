"""Operational alerts (ADR-0016): the fixed catalog, `render()` and the outbox insert.

Every alert that leaves the PC is one sentence from `CATALOG`, chosen by codes. Writers pass codes only, never
exception text or device names (a `ListenerLost` message names the microphone), so nothing a writer could fill
reaches Telegram; an unknown code renders as `UNKNOWN`. `leafi/ops/alerts.py::deliver` is the only sender.
"""

from __future__ import annotations

from leafi.core.storage import Store, now_iso

STATES = frozenset({"down", "up", "event"})

CATALOG: dict[tuple[str, str, str], str] = {
    ("camera", "down", "restart_gave_up"):
        "Leafi camera: go2rtc was restarted 3 times and the camera still sends no video. Restarts are paused; "
        "close the Mi Home app if it is open, check the camera, then press the go2rtc restart button.",
    ("camera", "up", "recovered"):
        "Leafi camera: video is back and has been steady for 10 minutes.",
    ("study-mic", "event", "mic_lost"):
        "Leafi reading session: the microphone stopped. The session continued on the keyboard or stopped; "
        "check the headset.",
    ("study-lease", "event", "lease_lost"):
        "Leafi reading session: another Leafi took over the speaker, so the session stopped. The reading is saved.",
    ("keeper-watchdog", "down", "repeated_exits"):
        "Leafi watchdog crashed 3 times in 30 minutes; camera recovery is not running. See data/logs on the PC.",
    ("keeper-habit-agent", "down", "repeated_exits"):
        "Leafi habit coach crashed 3 times in 30 minutes. See data/logs on the PC.",
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
