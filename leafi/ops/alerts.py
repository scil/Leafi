"""The one alert deliverer (ADR-0016): a toast for every new row at once, then Telegram oldest-first.

Toasts are local and shown once per row (best effort), never held behind Telegram. Telegram order is strict:
only the oldest unsent row is worked on, and while it waits for a retry nothing newer is sent, so a recovery
never reaches the owner before its outage; retries at 30 s, 2 min, 10 min, then hourly. Without Telegram a row
is done once its toast is shown. Concurrent deliverers (the supervisor and `alert --drain`) may rarely send a
row twice; accepted for v1.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from leafi.core import alerts
from leafi.core.storage import Store, now_iso

log = logging.getLogger("leafi.alerts")

RETRY_S = (30.0, 120.0, 600.0, 3600.0)
TOAST_TIMEOUT_S = 10.0
TOAST_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "win" / "toast.ps1"


async def deliver(store: Store, toast: Callable[[str], Awaitable[None]] | None, notifier,
                  now: Callable[[], float] = time.time) -> int:
    """Send what is due; returns how many rows were completed. Never raises for a channel failure."""
    done = 0
    telegram = notifier if notifier is not None and getattr(notifier, "can_send", False) else None
    if toast is not None:  # every new row gets its toast now, whatever Telegram's retry schedule says
        for row in store.all("SELECT * FROM alert_outbox WHERE toasted = 0 ORDER BY id"):
            try:
                await toast(alerts.render(row["key"], row["state"], row["reason"]))
            except Exception:  # noqa: BLE001 - a toast is best effort and never blocks Telegram
                log.warning("toast failed for alert %s", row["id"], exc_info=True)
            store.execute("UPDATE alert_outbox SET toasted = 1 WHERE id = ?", (row["id"],))
    while True:
        row = store.one("SELECT * FROM alert_outbox WHERE sent_at IS NULL ORDER BY id LIMIT 1")
        if row is None or row["next_try_at"] > now():
            return done
        text = alerts.render(row["key"], row["state"], row["reason"])
        if telegram is not None:
            try:
                await telegram.send(text)
            except Exception as e:  # noqa: BLE001 - transport error or non-2xx: retry later, keep order
                attempts = row["attempts"] + 1
                wait = RETRY_S[min(attempts, len(RETRY_S)) - 1]
                store.execute("UPDATE alert_outbox SET attempts = ?, next_try_at = ? WHERE id = ?",
                              (attempts, now() + wait, row["id"]))
                log.warning("telegram alert %s failed (%s); retry in %.0f s", row["id"], type(e).__name__, wait)
                return done
        store.execute("UPDATE alert_outbox SET sent_at = ? WHERE id = ?", (now_iso(), row["id"]))
        log.info("alert %s delivered: %s/%s/%s", row["id"], row["key"], row["state"], row["reason"])
        done += 1


async def windows_toast(text: str) -> None:
    """Toast through Windows PowerShell 5.1 (WinRT; PowerShell 7 cannot load it), bounded to 10 s."""
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOAST_SCRIPT),
        "-Title", "Leafi", "-Body", text,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), TOAST_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        raise
    if proc.returncode:
        raise RuntimeError(f"toast exited {proc.returncode}: {err.decode(errors='replace')[:200]}")
