"""`python -m leafi supervisor` (ADR-0016): keeps every independent Leafi service running, recovers one that
runs but does not answer, gives up after three recoveries per outage, and delivers the alert outbox.

Services (`SUPERVISE`): `camera` (the host go2rtc child), `habit-agent` (child), `docker` (Docker Desktop),
`frigate` and `mosquitto` (containers, observed only while Docker answers), `ollama` (child, off by default).
Child processes run inside a Windows Job Object each, with kill-on-close, so they die with the supervisor
however it dies. Each service's budget lives in `service_state` and is committed before the recovery. The camera
never fetches a frame unless something wants the stream: go2rtc is lazy, and each new connection asks Xiaomi's
cloud for keys.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from leafi.core import alerts
from leafi.core.storage import Store, now_iso

log = logging.getLogger("leafi.supervisor")

GOOD, BAD, IDLE = "GOOD", "BAD", "IDLE"
MAX_KILLS = 3
HEALTHY_S = 600.0       # ten continuous GOOD minutes end an outage
GRACE_RESUME_S = 120.0  # BAD is ignored this long after the PC resumes from sleep
RESUME_GAP_S = 180.0    # a wall-clock gap this long between polls is a resume
MIN_FRAME_BYTES = 1024
DELIVER_EVERY_S = 10.0


# ---------------------------------------------------------------- policy (pure apart from the store)

class ServicePolicy:
    """ADR-0016's policy for one service. `step()` returns True when the service must be recovered now; the
    caller recovers it and then calls `started()`. Budget, give-up and latch are persisted per service; streak
    and timers are not."""

    def __init__(self, store: Store, service: str, grace_s: float) -> None:
        self.store, self.service, self.grace_s = store, service, grace_s
        if store.one("SELECT service FROM service_state WHERE service = ?", (service,)) is None:
            store.insert("service_state", service=service, updated_at=now_iso())
        self.streak = 0
        self.good_since: float | None = None
        self.grace_until = 0.0
        self.last_wall: float | None = None

    def _state(self):
        return self.store.one("SELECT kills, gave_up, latch FROM service_state WHERE service = ?", (self.service,))

    def _set(self, sql: str) -> None:
        self.store.execute(f"UPDATE service_state SET {sql}, updated_at = ? WHERE service = ?",
                           (now_iso(), self.service))

    def started(self, mono: float) -> None:
        self.streak, self.good_since = 0, None
        self.grace_until = mono + self.grace_s

    def step(self, obs: str, mono: float, wall: float) -> bool:
        if self.last_wall is not None and wall - self.last_wall > RESUME_GAP_S:
            log.info("%s: resume detected (%.0f s gap)", self.service, wall - self.last_wall)
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
        return self._want_recovery() if self.streak >= 2 else False

    def rearm(self, mono: float) -> bool:
        """The 🔁 button: a fresh budget; its own recovery is attempt 1. The latch is kept (same outage)."""
        with self.store.transaction():
            self._set("kills = 0, gave_up = 0")
        log.info("%s: rearmed by the owner", self.service)
        return self._want_recovery("rearmed")

    def _want_recovery(self, cause: str = "not answering") -> bool:
        st = self._state()
        if st["gave_up"]:
            return False
        with self.store.transaction():
            if st["kills"] < MAX_KILLS:
                self._set("kills = kills + 1")
                log.warning("%s %s: recovery %d of %d", self.service, cause, st["kills"] + 1, MAX_KILLS)
                return True
            self._set("gave_up = 1, latch = 'down'")
            if st["latch"] == "up":
                alerts.insert(self.store, self.service, "down", "restart_gave_up")
        log.error("%s still failing after %d recoveries: paused until 10 good minutes or rearm", self.service,
                  MAX_KILLS)
        return False

    def _recovered(self) -> None:
        st = self._state()
        if not (st["kills"] or st["gave_up"] or st["latch"] == "down"):
            return
        with self.store.transaction():
            self._set("kills = 0, gave_up = 0, latch = 'up'")
            if st["latch"] == "down":
                alerts.insert(self.store, self.service, "up", "recovered")
        log.info("%s healthy for %.0f min: budget reset", self.service, HEALTHY_S / 60)


# ---------------------------------------------------------------- services and one poll

@dataclass
class Service:
    name: str
    grace_s: float
    observe: Callable[[], Awaitable[str]]
    recover: Callable[[], Awaitable[None]]
    depends_docker: bool = False


async def poll(services: list[Service], policies: dict[str, ServicePolicy], mono: float,
               wall: float) -> dict[str, str]:
    """Observe every service once, in order (docker first), and recover the ones whose policy asks for it.
    Containers are IDLE while Docker is not GOOD, so a stopped engine raises one alert, not three. Returns the
    observations (for the dashboard)."""
    docker_good = True
    seen: dict[str, str] = {}
    for svc in services:
        if svc.depends_docker and not docker_good:
            obs = IDLE
        else:
            try:
                obs = await svc.observe()
            except Exception:  # noqa: BLE001 - a broken probe is a bad observation, never a dead supervisor
                log.exception("%s: probe failed", svc.name)
                obs = BAD
        if svc.name == "docker":
            docker_good = obs == GOOD
        seen[svc.name] = obs
        if obs != GOOD:
            log.info("%s: %s", svc.name, obs)
        if policies[svc.name].step(obs, mono, wall):
            try:
                await svc.recover()
            except Exception:  # noqa: BLE001 - logged; the next polls decide again within the budget
                log.exception("%s: recovery failed", svc.name)
            policies[svc.name].started(mono)
    return seen


async def http_probe(client: httpx.AsyncClient, url: str, limit_s: float = 3) -> str:
    try:
        return GOOD if (await client.get(url, timeout=limit_s)).status_code == 200 else BAD
    except httpx.HTTPError:
        return BAD


async def tcp_probe(host: str, port: int, limit_s: float = 3) -> str:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), limit_s)
    except (OSError, TimeoutError):
        return BAD
    writer.close()
    return GOOD


async def observe_camera(client: httpx.AsyncClient, settings) -> str:
    """ADR-0016 camera observation, in order; a frame is fetched only when something wants the stream."""
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


async def _run(cmd: list[str], limit_s: float) -> int:
    def go() -> int:
        return subprocess.run(cmd, capture_output=True, timeout=limit_s, cwd=str(Path.cwd()),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode
    try:
        return await asyncio.to_thread(go)
    except (subprocess.TimeoutExpired, OSError):
        return -1


async def docker_probe() -> str:
    return GOOD if await _run(["docker", "info", "--format", "{{.ServerVersion}}"], 15) == 0 else BAD


async def compose_recover(name: str) -> None:
    """`up -d` recreates a removed container (a no-op for a running one); `restart` then kicks a hung one."""
    await _run(["docker", "compose", "up", "-d", name], 180)
    await _run(["docker", "compose", "restart", name], 120)


def docker_desktop_exe(settings) -> Path | None:
    if settings.docker_desktop_exe:
        return Path(settings.docker_desktop_exe)
    cli = shutil.which("docker")
    if not cli:
        return None
    for up in Path(cli).resolve().parents:  # scoop: …\docker\resources\bin\docker.exe → …\docker\Docker Desktop.exe
        cand = up / "Docker Desktop.exe"
        if cand.exists():
            return cand
    std = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")  # the standard installer's location
    return std if std.exists() else None


async def docker_recover(settings) -> None:
    """Restart Docker Desktop: end it if present (a hung engine), then start it, detached (Docker is not a child)."""
    exe = docker_desktop_exe(settings)
    if exe is None:
        log.error("docker: Docker Desktop executable not found; set DOCKER_DESKTOP_EXE")
        return
    await _run(["taskkill", "/IM", "Docker Desktop.exe", "/T", "/F"], 30)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    await asyncio.to_thread(subprocess.Popen, [str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True)


# ---------------------------------------------------------------- rearm endpoint

async def serve_rearm(host: str, port: int, on_rearm: Callable[[str], None],
                      services: set[str]) -> asyncio.base_events.Server:
    """A minimal HTTP listener: `POST /rearm[?service=S]` (default camera) → 200 and `on_rearm(S)`; anything
    else → 404. Nothing else can reach the supervisor, so nothing outside Leafi can insert an alert."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            line = head.split(b"\r\n", 1)[0].split()
            target = line[1].decode("latin-1") if len(line) >= 2 else ""
            path, _, query = target.partition("?")
            params = dict(p.partition("=")[::2] for p in query.split("&") if p)
            service = params.get("service", "camera")
            hit = line[:1] == [b"POST"] and path == "/rearm" and service in services
            if hit:
                on_rearm(service)
            status = b"200 OK" if hit else b"404 Not Found"
            writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)


# ---------------------------------------------------------------- child processes in Job Objects

class Job:
    """A Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: closing it (or the supervisor dying) kills
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


class Child:
    """One supervised child process (ADR-0016 rule 1): the supervisor is its only owner."""

    def __init__(self, name: str, argv: list[str], out_log: logging.Logger, stray: Callable[[str, str], bool]) -> None:
        self.name, self.argv, self.out_log, self.stray = name, argv, out_log, stray
        self.proc: subprocess.Popen | None = None
        self.job: Job | None = None

    def kill_strays(self) -> None:
        """Kill instances we did not start; `stray(executable_path, command_line)` recognises them."""
        own = self.proc.pid if self.proc else None
        query = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } | "
                 "ForEach-Object { \"$($_.ProcessId)`t$($_.ExecutablePath)`t$($_.CommandLine)\" }")
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", query], capture_output=True, text=True,
                             timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        for line in out.splitlines():
            pid, _, rest = line.partition("\t")
            path, _, cmdline = rest.partition("\t")
            if pid.strip().isdigit() and int(pid) not in (own, os.getpid()) and self.stray(path, cmdline):
                log.warning("%s: killing an instance we do not own (pid %s)", self.name, pid)
                subprocess.run(["taskkill", "/PID", pid.strip(), "/T", "/F"], capture_output=True, timeout=30)

    def start(self) -> None:
        job = Job()
        proc = subprocess.Popen(self.argv, cwd=str(Path.cwd()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(proc)
        self.proc, self.job = proc, job
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        log.info("%s started (pid %d)", self.name, proc.pid)

    def stop(self) -> None:
        if self.job is not None:
            self.job.close()  # kill-on-close: the child and everything it spawned
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
    """Exclusive lock for the supervisor's lifetime; a second instance exits at once."""
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")  # noqa: SIM115 - held open for the process lifetime
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    return fh


def _same_file(a: str, b: Path) -> bool:
    try:
        return bool(a) and Path(a).resolve() == b.resolve()
    except OSError:
        return False


def build(settings, client: httpx.AsyncClient, logs: Path) -> tuple[list[Service], list[Child]]:
    """The enabled services, docker first (containers depend on it), and the children to start."""
    enabled = [s.strip() for s in settings.supervise.split(",") if s.strip()]
    services: list[Service] = []
    children: list[Child] = []
    py = Path(sys.executable)

    def child(name: str, argv: list[str], stray: Callable[[str, str], bool]) -> Child:
        out = _rotating(logs / f"{name}.log", f"child.{name}", "%(asctime)s %(message)s")
        out.propagate = False
        c = Child(name, argv, out, stray)
        children.append(c)
        return c

    if "docker" in enabled:
        services.append(Service("docker", 180.0, docker_probe, lambda: docker_recover(settings)))
    if "camera" in enabled:
        exe = Path(settings.go2rtc_exe)
        go2rtc = child("go2rtc", [str(exe.resolve()), "-config", str(settings.go2rtc_config)],
                       lambda path, cmd: _same_file(path, exe))

        async def observe_cam() -> str:
            return await observe_camera(client, settings) if go2rtc.alive() else BAD

        services.append(Service("camera", 90.0, observe_cam, lambda: asyncio.to_thread(go2rtc.restart)))
    if "habit-agent" in enabled:
        agent = child("habit-agent", [str(py), "-m", "agent.main"],
                      lambda path, cmd: "-m agent.main" in cmd and "python" in Path(path).name.lower())

        async def observe_agent() -> str:
            return GOOD if agent.alive() else BAD

        services.append(Service("habit-agent", 90.0, observe_agent, lambda: asyncio.to_thread(agent.restart)))
    for name, grace, probe in (
            ("frigate", 120.0, lambda: http_probe(client, f"{settings.frigate_url.rstrip('/')}/api/stats")),
            ("mosquitto", 60.0, lambda: tcp_probe("127.0.0.1", settings.mqtt_port)),
            ("gatus", 60.0, lambda: http_probe(client, f"{settings.gatus_url.rstrip('/')}/health"))):
        if name in enabled:
            services.append(Service(name, grace, probe, lambda n=name: compose_recover(n), depends_docker=True))
    if "ollama" in enabled:
        ollama_exe = shutil.which("ollama") or "ollama"
        ollama = child("ollama", [ollama_exe, "serve"], lambda path, cmd: " serve" in cmd and
                       Path(path).stem.lower() == "ollama")

        async def observe_ollama() -> str:
            if not ollama.alive():
                return BAD
            return await http_probe(client, f"{settings.ollama_url.rstrip('/')}/api/tags")

        services.append(Service("ollama", 60.0, observe_ollama, lambda: asyncio.to_thread(ollama.restart)))
    return services, children


async def run(settings) -> int:
    from leafi.devices.notifiers import NotifierDevice
    from leafi.ops import checks
    from leafi.ops.alerts import deliver, windows_toast

    logs = Path(settings.data_dir) / "logs"
    lock = _single_instance(Path(settings.data_dir) / "supervisor.lock")
    if lock is None:
        print("another supervisor is running; exiting", file=sys.stderr)
        return 3
    _rotating(logs / "supervisor.log", "leafi", "%(asctime)s %(name)s %(levelname)s %(message)s")

    store = Store(settings.db_path)
    notifier = NotifierDevice(options={"telegram_bot_token": settings.telegram_bot_token,
                                       "telegram_chat_id": settings.telegram_chat_id})
    loop = asyncio.get_running_loop()
    rearms: asyncio.Queue[str] = asyncio.Queue()

    async with httpx.AsyncClient() as client:
        services, children = build(settings, client, logs)
        by_name = {s.name: s for s in services}
        policies = {s.name: ServicePolicy(store, s.name, s.grace_s) for s in services}
        server = await serve_rearm("127.0.0.1", settings.supervisor_port,
                                   lambda s: loop.call_soon_threadsafe(rearms.put_nowait, s), set(by_name))

        async def delivery() -> None:
            while True:
                try:
                    await deliver(store, windows_toast, notifier)
                except Exception:  # noqa: BLE001 - delivery must never stop the supervisor
                    log.exception("alert delivery failed")
                await asyncio.sleep(DELIVER_EVERY_S)

        runner = checks.CheckRunner(store, checks.build(settings))

        async def checking() -> None:
            while True:
                try:
                    for name, ok in (await runner.run_all()).items():
                        if ok is not None:
                            await checks.push(client, settings.gatus_url, settings.gatus_token, "checks", name, ok,
                                              "" if ok else "failed")
                except Exception:  # noqa: BLE001 - checks must never stop the supervisor
                    log.exception("configuration checks failed")
                await asyncio.sleep(settings.checks_every_s)

        async def report(seen: dict[str, str]) -> None:
            """Heartbeat (dead man's switch) and the read-only dashboard; neither can fail the poll."""
            await checks.heartbeat(client, settings.heartbeat_url)
            await checks.push(client, settings.gatus_url, settings.gatus_token, "leafi", "supervisor", True, "")
            for name, obs in seen.items():
                await checks.push(client, settings.gatus_url, settings.gatus_token, "services", name, obs != BAD,
                                  obs)

        for c in children:  # initial start: uncharged, even for a service whose budget has given up (ADR-0016)
            await asyncio.to_thread(c.kill_strays)
            c.start()
        for p in policies.values():
            p.started(time.monotonic())
        sender = asyncio.create_task(delivery())
        checker = asyncio.create_task(checking())
        log.info("supervisor up: pid %d, services %s, rearm on 127.0.0.1:%d", os.getpid(), ",".join(by_name),
                 settings.supervisor_port)
        try:
            next_poll = time.monotonic()
            while True:
                try:
                    name = await asyncio.wait_for(rearms.get(), max(0.0, next_poll - time.monotonic()))
                except TimeoutError:
                    await report(await poll(services, policies, time.monotonic(), time.time()))
                    next_poll = time.monotonic() + settings.supervisor_poll_s
                    continue
                if policies[name].rearm(time.monotonic()):
                    try:
                        await by_name[name].recover()
                    except Exception:  # noqa: BLE001
                        log.exception("%s: recovery after rearm failed", name)
                    policies[name].started(time.monotonic())
        finally:
            sender.cancel()
            checker.cancel()
            server.close()
            for c in children:
                c.stop()
            lock.close()
