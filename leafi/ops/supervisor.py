"""`python -m leafi watchdog` (ADR-0016): owns the host go2rtc, restarts it when the camera sends no video,
gives up after three restarts per outage, and delivers the alert outbox.

go2rtc runs inside a Windows Job Object with kill-on-close, one job per generation, so it (and any ffmpeg it
spawned for a speaker push) dies with the watchdog however the watchdog dies. The restart budget lives in the
`watchdog_state` row and is committed before the kill. The watchdog never fetches a frame unless something
wants the stream (a consumer, or Frigate listing the camera): go2rtc is lazy, and each new connection asks
Xiaomi's cloud for keys.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from leafi.core import alerts
from leafi.core.storage import Store, now_iso

log = logging.getLogger("leafi.watchdog")

GOOD, BAD, IDLE = "GOOD", "BAD", "IDLE"
MAX_KILLS = 3
HEALTHY_S = 600.0       # ten continuous GOOD minutes end an outage
GRACE_START_S = 90.0    # BAD is ignored this long after go2rtc starts
GRACE_RESUME_S = 120.0  # … and after the PC resumes from sleep
RESUME_GAP_S = 180.0    # a wall-clock gap this long between polls is a resume
MIN_FRAME_BYTES = 1024
DELIVER_EVERY_S = 10.0


# ---------------------------------------------------------------- state machine (pure apart from the store)

class CameraPolicy:
    """ADR-0016's camera state machine. `step()` returns True when go2rtc must be restarted now; the caller
    restarts it and then calls `started()`. Budget, give-up and latch are persisted; streak and timers are not."""

    def __init__(self, store: Store) -> None:
        self.store = store
        if store.one("SELECT id FROM watchdog_state WHERE id = 1") is None:
            store.insert("watchdog_state", id=1, updated_at=now_iso())
        self.streak = 0
        self.good_since: float | None = None
        self.grace_until = 0.0
        self.last_wall: float | None = None

    def _state(self):
        return self.store.one("SELECT kills, gave_up, latch FROM watchdog_state WHERE id = 1")

    def started(self, mono: float) -> None:
        self.streak, self.good_since = 0, None
        self.grace_until = mono + GRACE_START_S

    def step(self, obs: str, mono: float, wall: float) -> bool:
        if self.last_wall is not None and wall - self.last_wall > RESUME_GAP_S:
            log.info("resume detected (%.0f s gap): grace %.0f s", wall - self.last_wall, GRACE_RESUME_S)
            self.streak, self.good_since = 0, None
            self.grace_until = max(self.grace_until, mono + GRACE_RESUME_S)
        self.last_wall = wall
        if obs == IDLE:
            self.streak, self.good_since = 0, None
            return False
        if obs == GOOD:
            self.streak = 0
            if self.good_since is None:
                self.good_since = mono
            if mono - self.good_since >= HEALTHY_S:
                self._recovered()
            return False
        self.good_since = None
        if mono < self.grace_until:
            return False
        self.streak += 1
        return self._want_restart() if self.streak >= 2 else False

    def rearm(self, mono: float) -> bool:
        """The 🔁 button: a fresh budget; its own restart is attempt 1. The latch is kept (same outage)."""
        with self.store.transaction():
            self.store.execute("UPDATE watchdog_state SET kills = 0, gave_up = 0, updated_at = ? WHERE id = 1",
                               (now_iso(),))
        log.info("rearmed by the owner")
        return self._want_restart("rearmed")

    def _want_restart(self, cause: str = "camera broken") -> bool:
        st = self._state()
        if st["gave_up"]:
            return False
        with self.store.transaction():
            if st["kills"] < MAX_KILLS:
                self.store.execute("UPDATE watchdog_state SET kills = kills + 1, updated_at = ? WHERE id = 1",
                                   (now_iso(),))
                log.warning("%s: restart %d of %d", cause, st["kills"] + 1, MAX_KILLS)
                return True
            self.store.execute("UPDATE watchdog_state SET gave_up = 1, latch = 'down', updated_at = ? WHERE id = 1",
                               (now_iso(),))
            if st["latch"] == "up":
                alerts.insert(self.store, "camera", "down", "restart_gave_up")
        log.error("camera still broken after %d restarts: restarts paused until 10 good minutes or 🔁", MAX_KILLS)
        return False

    def _recovered(self) -> None:
        st = self._state()
        if not (st["kills"] or st["gave_up"] or st["latch"] == "down"):
            return
        with self.store.transaction():
            self.store.execute("UPDATE watchdog_state SET kills = 0, gave_up = 0, latch = 'up', updated_at = ? "
                               "WHERE id = 1", (now_iso(),))
            if st["latch"] == "down":
                alerts.insert(self.store, "camera", "up", "recovered")
        log.info("camera healthy for %.0f min: budget reset", HEALTHY_S / 60)


# ---------------------------------------------------------------- one observation

async def observe(client: httpx.AsyncClient, settings) -> str:
    """ADR-0016 observe steps, in order; a frame is fetched only when something wants the stream."""
    base, name = settings.go2rtc_url.rstrip("/"), settings.stream_name
    try:
        r = await client.get(f"{base}/api/streams", timeout=3)
        r.raise_for_status()
        stream = (r.json() or {}).get(name) or {}
    except (httpx.HTTPError, ValueError):
        return BAD
    consumers = stream.get("consumers") or []
    demand = bool(consumers) or await _frigate_lists_camera(client, settings)
    if not demand:
        return IDLE
    if not any(p.get("remote_addr") for p in stream.get("producers") or []):
        return BAD
    try:
        f = await client.get(f"{base}/api/frame.jpeg", params={"src": name}, timeout=15)
    except httpx.HTTPError:
        return BAD
    ok = f.status_code == 200 and len(f.content) >= MIN_FRAME_BYTES and f.content[:2] == b"\xff\xd8"
    return GOOD if ok else BAD


async def _frigate_lists_camera(client: httpx.AsyncClient, settings) -> bool:
    try:
        r = await client.get(f"{settings.frigate_url.rstrip('/')}/api/stats", timeout=3)
        return r.status_code == 200 and settings.frigate_camera in ((r.json() or {}).get("cameras") or {})
    except (httpx.HTTPError, ValueError):
        return False


# ---------------------------------------------------------------- rearm endpoint

async def serve_rearm(host: str, port: int, on_rearm: Callable[[], None]) -> asyncio.base_events.Server:
    """A minimal HTTP listener: `POST /rearm` → 200 and `on_rearm()`; anything else → 404. Nothing else can
    reach the watchdog, so nothing outside Leafi can insert an alert."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            line = head.split(b"\r\n", 1)[0].split()
            hit = len(line) >= 2 and line[0] == b"POST" and line[1].split(b"?")[0] == b"/rearm"
            if hit:
                on_rearm()
            status = b"200 OK" if hit else b"404 Not Found"
            writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)


# ---------------------------------------------------------------- go2rtc process in a Job Object

class Job:
    """A Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: closing it (or the watchdog dying) kills
    every process assigned to it, including their children."""

    def __init__(self) -> None:
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, proc: subprocess.Popen) -> None:
        if not self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


class Go2rtc:
    """The one owner of the host go2rtc process (ADR-0016 rule 1)."""

    def __init__(self, settings, out_log: logging.Logger) -> None:
        self.exe = Path(settings.go2rtc_exe).resolve()
        self.config = Path(settings.go2rtc_config)
        self.out_log = out_log
        self.proc: subprocess.Popen | None = None
        self.job: Job | None = None

    def kill_strays(self) -> None:
        """Kill a go2rtc.exe at this repository's path that we did not start (e.g. from go2rtc-host.bat)."""
        own = self.proc.pid if self.proc else None
        query = ("Get-CimInstance Win32_Process -Filter \"Name='go2rtc.exe'\" | "
                 "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }")
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", query], capture_output=True, text=True,
                             timeout=30).stdout
        for line in out.splitlines():
            pid, _, path = line.partition("|")
            if pid.strip().isdigit() and int(pid) != own and path and Path(path).resolve() == self.exe:
                log.warning("killing a go2rtc we do not own (pid %s)", pid)
                subprocess.run(["taskkill", "/PID", pid.strip(), "/T", "/F"], capture_output=True, timeout=30)

    def start(self) -> None:
        job = Job()
        proc = subprocess.Popen([str(self.exe), "-config", str(self.config)], cwd=str(Path.cwd()),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(proc)
        self.proc, self.job = proc, job
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        log.info("go2rtc started (pid %d)", proc.pid)

    def stop(self) -> None:
        if self.job is not None:
            self.job.close()  # kill-on-close: go2rtc and its ffmpeg children
        if self.proc is not None:
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.job = None, None

    def restart(self) -> None:
        self.stop()
        self.start()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _pump(self, proc: subprocess.Popen) -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            self.out_log.info(raw.decode("utf-8", "replace").rstrip())


# ---------------------------------------------------------------- the process

def _rotating(path: Path, name: str, fmt: str) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(fmt))
    lg = logging.getLogger(name)
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    return lg


def _single_instance(path: Path):
    """Exclusive lock for the watchdog's lifetime; a second instance exits at once."""
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")  # noqa: SIM115 - held open for the process lifetime
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    return fh


async def run(settings) -> int:
    from leafi.devices.notifiers import NotifierDevice
    from leafi.ops.alerts import deliver, windows_toast

    logs = Path(settings.data_dir) / "logs"
    lock = _single_instance(Path(settings.data_dir) / "watchdog.lock")
    if lock is None:
        print("another watchdog is running; exiting", file=sys.stderr)
        return 3
    fmt = "%(asctime)s %(levelname)s %(message)s"
    _rotating(logs / "watchdog.log", "leafi", "%(asctime)s %(name)s %(levelname)s %(message)s")
    out_log = _rotating(logs / "go2rtc.log", "go2rtc.out", fmt)
    out_log.propagate = False

    store = Store(settings.db_path)
    policy = CameraPolicy(store)
    go2rtc = Go2rtc(settings, out_log)
    notifier = NotifierDevice(options={"telegram_bot_token": settings.telegram_bot_token,
                                       "telegram_chat_id": settings.telegram_chat_id})
    loop = asyncio.get_running_loop()
    rearm_requested = asyncio.Event()
    server = await serve_rearm("127.0.0.1", settings.watchdog_port,
                               lambda: loop.call_soon_threadsafe(rearm_requested.set))

    async def delivery() -> None:
        while True:
            try:
                await deliver(store, windows_toast, notifier)
            except Exception:  # noqa: BLE001 - delivery must never stop the watchdog
                log.exception("alert delivery failed")
            await asyncio.sleep(DELIVER_EVERY_S)

    await asyncio.to_thread(go2rtc.kill_strays)
    go2rtc.start()
    policy.started(time.monotonic())
    sender = asyncio.create_task(delivery())
    log.info("watchdog up: pid %d, stream %s, rearm on 127.0.0.1:%d", os.getpid(), settings.stream_name,
             settings.watchdog_port)
    try:
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    await asyncio.wait_for(rearm_requested.wait(), settings.watchdog_poll_s)
                except TimeoutError:
                    pass
                if rearm_requested.is_set():
                    rearm_requested.clear()
                    if policy.rearm(time.monotonic()):
                        await asyncio.to_thread(go2rtc.restart)
                        policy.started(time.monotonic())
                    continue
                if not go2rtc.alive():
                    log.warning("go2rtc exited (code %s): starting it (not a charged restart)",
                                go2rtc.proc.returncode if go2rtc.proc else None)
                    await asyncio.to_thread(go2rtc.restart)
                    policy.started(time.monotonic())
                    continue
                obs = await observe(client, settings)
                log.info("observation %s", obs)
                if policy.step(obs, time.monotonic(), time.time()):
                    await asyncio.to_thread(go2rtc.restart)
                    policy.started(time.monotonic())
    finally:
        sender.cancel()
        server.close()
        go2rtc.stop()
        lock.close()
