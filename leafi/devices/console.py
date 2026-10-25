"""Typed console device: a Listener that yields typed Utterances and a Face that prints (H4).

Always safe to leave on. stdin is read by one daemon thread started on the first read (no import-time
side effects). End of input becomes `/stop`, unless the option `eof_stops` is false: then the console simply goes
quiet (a session driven from the session panel without a terminal, panel design D2). Tests pass `lines=[...]`
instead of stdin.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Iterable
from typing import TextIO

from leafi.core.ports import Display, Utterance
from leafi.core.text import typed_utterance

_EOF = object()


class ConsoleDevice:
    is_voice = False

    def __init__(self, name: str = "console", options: dict | None = None, settings=None, *,
                 lines: Iterable[str] | None = None, stdin: TextIO | None = None,
                 stdout: TextIO | None = None) -> None:
        self.name = name
        self.options = options or {}
        self._script = list(lines) if lines is not None else None
        self._stdin = stdin
        self._stdout = stdout
        self._queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self.shown: list[Display] = []

    # ---- Listener
    async def next_utterance(self, timeout_s: float | None) -> Utterance | None:
        if self._script is not None:
            line, t = (self._script.pop(0) if self._script else _EOF), None  # a script: stamped on delivery
        else:
            q = self._ensure_reader()
            try:
                line, t = await asyncio.wait_for(q.get(), timeout_s) if timeout_s else await q.get()
            except TimeoutError:
                return None
        if line is _EOF:
            if not self.options.get("eof_stops", True):
                await asyncio.Event().wait()  # quiet from now on; the session's cancellation ends the wait
            return typed_utterance("/stop", self.name, t)
        return typed_utterance(str(line).rstrip("\r\n"), self.name, t)

    async def pause(self) -> None:  # typed input cannot hear Leafi; nothing to discard
        return None

    async def resume(self, after_s: float = 0.0) -> None:
        return None

    def _ensure_reader(self) -> asyncio.Queue:
        if self._queue is None:
            loop = asyncio.get_running_loop()
            self._queue = asyncio.Queue()
            stream = self._stdin or sys.stdin
            q = self._queue

            # On a terminal each line is stamped when Enter was pressed, not when a listen took it (D21). Piped
            # input is read ahead all at once, so a stamp would date every line to the start: it stays None and
            # Inputs stamps it on delivery, as M6 took it (a script answers each listen in turn).
            tty = bool(getattr(stream, "isatty", lambda: False)())

            def run() -> None:
                for raw in iter(stream.readline, ""):
                    loop.call_soon_threadsafe(q.put_nowait, (raw, time.monotonic() if tty else None))
                loop.call_soon_threadsafe(q.put_nowait, (_EOF, None))

            self._thread = threading.Thread(target=run, name="console-stdin", daemon=True)
            self._thread.start()
        return self._queue

    # ---- Face
    async def show(self, msg: Display) -> None:
        self.shown.append(msg)
        out = self._stdout or sys.stdout
        if msg.kind == "listening":
            # On an interactive terminal a visible prompt is the listening indicator; piped input gets none.
            stream = self._stdin or sys.stdin
            if self._script is None and getattr(stream, "isatty", lambda: False)():
                out.write("> ")
                out.flush()
            return
        prefix = {"say": "Leafi", "status": "  ·", "listening": "  ~", "alert": "  !"}[msg.kind]
        try:
            out.write(f"{prefix}: {msg.text}\n" if msg.kind == "say" else f"{prefix} {msg.text}\n")
            out.flush()
        except (UnicodeEncodeError, ValueError):
            out.write(msg.text.encode("ascii", "replace").decode() + "\n")
