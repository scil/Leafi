"""The session panel device (session panel design rev 5, D1 and D4): a Face and a typed Listener with a loopback HTTP
endpoint, so the web UI's Reading tab can show the running session and send typed lines into it.

- Face: every `Display` goes into a ring buffer (it never prints).
- Listener: `is_voice = False`, `main_capable = False` (it never leads the session, ADR-0017 §1 as amended),
  `always_read = True` (Inputs reads it again after every line, so a press is taken at once). Each line is an
  `Utterance(source="panel")` stamped with the publish time of the snapshot the owner acted on, so the prompt that
  was on the owner's screen owns it (M7 design D21).
- Endpoint: a stdlib `ThreadingHTTPServer` on 127.0.0.1 in a daemon thread, started by `start()` once the speech
  lease is held. The thread never touches session objects: the loop publishes the snapshot as bytes by replacing
  one reference, and a POST goes to the loop with `call_soon_threadsafe`. Every request needs the bearer token, a
  loopback Host and no Origin; a POST also the session id, a line from the fixed command list, and an accepting
  session.
- Runtime file: `<data>/run/study-panel-<pid>.json` (port, token, session) for the web UI; the device removes its own
  and sweeps those of dead processes; a reader never deletes one.
- Faults stay here: the device disables itself, logs, and tries one alert; nothing reaches the session.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from leafi.core.ports import Display, Utterance
from leafi.core.storage import now_iso
from leafi.core.text import typed_utterance

log = logging.getLogger("leafi.devices.panel")

PANEL = "panel"  # the `Utterance.source` of a panel line (the study track's `controls.PANEL`)
SCHEMA = 1        # the runtime file's version
SHOWN = 200       # lines kept from the Faces
REFRESH_S = 0.2   # at most one snapshot per this; a trailing one catches the last change
MAX_BODY = 2048
MAX_LINE = 500
STALE_SEEN_S = 60.0
# The fixed command list (design D6); `/say` text never starts with `/`, `/do` names a kind
ALLOWED = re.compile(r"^/(skip|stop|next|yes|no|know|again|hard|good|easy)$"
                     r"|^/page \d+ --text \S+$|^/fix \S+ \S.*$|^/say [^/\s].*$|^/do [a-z_]+$")


# ---------------------------------------------------------------- the runtime file (design D4)


def runtime_files(run_dir: Path) -> list[dict]:
    """Every readable `study-panel-*.json` under `run_dir`, newest first; a partial or foreign file is skipped."""
    out = []
    for path in Path(run_dir).glob("study-panel-*.json"):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(info, dict) and info.get("schema") == SCHEMA:
            out.append(info | {"path": str(path)})
    return sorted(out, key=lambda i: str(i.get("started_at", "")), reverse=True)


def live(info: dict) -> bool:
    """The file's process still runs: its pid is alive with the same start time (a reused pid fails)."""
    import psutil

    from leafi.core.lease import pid_alive

    pid = info.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return False
    try:
        return int(psutil.Process(pid).create_time()) == int(info.get("create_time", -1))
    except (psutil.Error, ValueError, TypeError):
        return False


def sweep(run_dir: Path, keep: Path | None = None) -> None:
    """Remove the runtime files of processes that are gone (only the writers do this, never the web UI)."""
    for info in runtime_files(run_dir):
        path = Path(info["path"])
        if path != keep and not live(info):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.info("stale panel file %s not removed", path.name)


# ---------------------------------------------------------------- HTTP


class _Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"  # SO_REUSEADDR lets another socket take the port on Windows
    daemon_threads = True

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)  # no getfqdn(): a loopback name needs no lookup
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    def handle_error(self, request, client_address) -> None:
        log.warning("panel request failed", exc_info=True)


class _Handler(BaseHTTPRequestHandler):
    device: PanelDevice

    def log_message(self, fmt, *args) -> None:
        log.debug("panel %s", fmt % args)

    def _reply(self, code: int, body: bytes = b"", ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _allowed(self) -> bool:
        d = self.device
        if self.headers.get("Host", "") not in (f"127.0.0.1:{d.port}", f"localhost:{d.port}"):
            return False  # DNS rebinding
        if self.headers.get("Origin") is not None:
            return False  # only a browser sends one, and no browser is meant to reach this hop
        try:
            return secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {d.token}")
        except TypeError:  # a non-ASCII header
            return False

    def do_GET(self) -> None:
        if not self._allowed():
            return self._reply(403)
        parts = urlsplit(self.path)
        if parts.path != "/status":
            return self._reply(404)
        version, _t, body = self.device.published
        if parse_qs(parts.query).get("since", [None])[0] == version:
            return self._reply(204)
        return self._reply(200, body)

    def do_POST(self) -> None:
        if not self._allowed():
            return self._reply(403)
        if urlsplit(self.path).path != "/input":
            return self._reply(404)
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._reply(411)
        if n > MAX_BODY:
            return self._reply(413)
        try:
            data = json.loads(self.rfile.read(n))
        except ValueError:
            return self._reply(400)
        line = data.get("line") if isinstance(data, dict) else None
        if not isinstance(line, str) or not line.strip() or "\r" in line or "\n" in line or len(line) > MAX_LINE \
                or not ALLOWED.match(line):
            return self._reply(400)
        d = self.device
        if data.get("session_id") != d.session_id or not d.accepting:
            return self._reply(409)  # never another session's, never an ending one's
        seen = data.get("seen")
        if not d.post(line, seen if isinstance(seen, int | float) and not isinstance(seen, bool) else None):
            return self._reply(503)
        return self._reply(202)


# ---------------------------------------------------------------- the device


class PanelDevice:
    is_voice = False
    main_capable = False
    always_read = True

    def __init__(self, name: str = "panel", options: dict | None = None, settings=None) -> None:
        self.name = name
        self.options = options or {}
        self.port_setting = int(self.options.get("port", getattr(settings, "study_panel_port", 0) or 0))
        self.run_dir = Path(self.options.get("run_dir") or Path(getattr(settings, "data_dir", "data")) / "run")
        self.token = secrets.token_urlsafe(32)
        self.session_id: int | None = None
        self.port: int | None = None
        self.accepting = False  # read by the serving thread; the loop sets it
        self.published: tuple[str, float, bytes] = ("0:0", 0.0, b"{}")  # replaced whole by the loop
        self.shown: deque[tuple[float, str, str]] = deque(maxlen=SHOWN)
        self.dead = False
        self._queue: asyncio.Queue = asyncio.Queue()
        self._queued: list[str] = []  # posted, not yet read by the session
        self._snapshot: Callable[[], dict] | None = None
        self._store = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._file: Path | None = None
        self._n = 0
        self._last = 0.0
        self._trailing: asyncio.TimerHandle | None = None
        self._closed = False

    # ---- Face
    async def show(self, msg: Display) -> None:
        self.shown.append((time.monotonic(), msg.kind, msg.text))
        self.mark_dirty()

    # ---- Listener
    async def next_utterance(self, timeout_s: float | None) -> Utterance | None:
        self.mark_dirty()
        if self.dead:
            await asyncio.Event().wait()  # a dead panel delivers nothing; the session goes on
        try:
            line, seen = await (asyncio.wait_for(self._queue.get(), timeout_s) if timeout_s else self._queue.get())
        except TimeoutError:
            return None
        if line in self._queued:
            self._queued.remove(line)
        self.mark_dirty()
        now = time.monotonic()
        stamp = seen if seen is not None and now - STALE_SEEN_S <= seen <= now else now
        return typed_utterance(line, PANEL, stamp)

    async def pause(self) -> None:  # typed input cannot hear Leafi
        return None

    async def resume(self, after_s: float = 0.0) -> None:
        return None

    # ---- lifecycle (on the loop thread)
    def start(self, snapshot: Callable[[], dict], *, session_id: int, store=None) -> None:
        """Bind, serve, write the runtime file; called once the speech lease is held. Never raises."""
        self._snapshot, self.session_id, self._store = snapshot, session_id, store
        self._loop = asyncio.get_running_loop()
        self.accepting = True
        try:
            sweep(self.run_dir)
            handler = type("PanelHandler", (_Handler,), {"device": self})
            self._server = _Server(("127.0.0.1", self.port_setting), handler)
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(target=self._serve, name="session-panel", daemon=True)
            self._thread.start()
            self._write_file()
            log.info("session panel on 127.0.0.1:%s", self.port)
        except Exception as e:  # noqa: BLE001 - a panel fault never reaches the session
            self._fault(e)
        self.refresh()

    def _serve(self) -> None:
        try:
            self._server.serve_forever(poll_interval=0.2)
        except Exception as e:  # noqa: BLE001
            self._to_loop(self._fault, e)

    def _to_loop(self, fn, *args) -> bool:
        if self._loop is None:
            return False
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:  # the loop is closed: the session is over
            return False
        return True

    def _fault(self, err: BaseException) -> None:
        if self.dead:
            return
        self.dead = True  # first: nothing more is delivered
        log.error("session panel failed: %s", err)
        try:
            from leafi.core import alerts

            if self._store is not None:
                alerts.insert(self._store, "study-panel", "event", "panel_failed")
        except Exception:  # noqa: BLE001 - a busy store keeps the log line only
            log.warning("panel alert not written", exc_info=True)

    def _write_file(self) -> None:
        import psutil

        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / f"study-panel-{os.getpid()}.json"
        info = {"schema": SCHEMA, "pid": os.getpid(), "create_time": psutil.Process().create_time(),
                "port": self.port, "token": self.token, "session_id": self.session_id, "started_at": now_iso()}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        os.replace(tmp, path)
        self._file = path

    async def close(self) -> None:
        """Idempotent: stop serving (only a server whose thread runs), close, remove the own file."""
        if self._closed:
            return
        self._closed = True
        self.accepting = False
        if self._trailing is not None:
            self._trailing.cancel()
        server, thread = self._server, self._thread
        if server is not None:
            if thread is not None and thread.is_alive():
                import anyio

                await anyio.to_thread.run_sync(server.shutdown)  # never on the serving thread (it deadlocks)
            server.server_close()
        if self._file is not None:
            for _ in range(2):
                try:
                    self._file.unlink(missing_ok=True)
                    break
                except OSError:  # the web UI reading it on Windows
                    await asyncio.sleep(0.05)

    # ---- publishing (on the loop thread)
    def mark_dirty(self) -> None:
        if self._snapshot is None or self._closed:
            return
        wait = REFRESH_S - (time.monotonic() - self._last)
        if wait <= 0:
            self.refresh()
        elif self._trailing is None and self._loop is not None:
            self._trailing = self._loop.call_later(wait, self._trail)

    def _trail(self) -> None:
        self._trailing = None
        self.refresh()

    def refresh(self) -> None:
        if self._snapshot is None:
            return
        try:
            snap = self._snapshot()
        except Exception:  # noqa: BLE001 - the old snapshot stays
            log.warning("panel snapshot failed", exc_info=True)
            return
        self._n += 1
        publish_t = time.monotonic()
        version = f"{self.session_id}:{self._n}"
        body = {"version": version, "publish_t": publish_t, "session_id": self.session_id, **snap,
                "queued": list(self._queued), "panel": {"dead": self.dead},
                "shown": [{"kind": k, "text": t} for _at, k, t in list(self.shown)[-40:] if k != "listening"]}
        self.accepting = bool(snap.get("io", {}).get("accepting", True)) and not self._closed
        self.published = (version, publish_t, json.dumps(body, default=str).encode("utf-8"))
        self._last = publish_t

    def post(self, line: str, seen: float | None) -> bool:
        """From the serving thread: hand a line to the loop."""
        return self._to_loop(self._take, line, seen)

    def _take(self, line: str, seen: float | None) -> None:
        self._queued.append(line)
        self._queue.put_nowait((line, seen))
        self.mark_dirty()
