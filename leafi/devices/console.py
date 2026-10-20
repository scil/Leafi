"""Typed console device: a Listener that yields typed Utterances and a Face that prints (H4).

Always safe to leave on. stdin is read by one daemon thread started on the first read (no import-time
side effects). End of input becomes `/stop`. Tests pass `lines=[...]` instead of stdin.
"""

from __future__ import annotations

import asyncio
import sys
import threading
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
            line = self._script.pop(0) if self._script else _EOF
        else:
            q = self._ensure_reader()
            try:
                line = await asyncio.wait_for(q.get(), timeout_s) if timeout_s else await q.get()
            except TimeoutError:
                return None
        if line is _EOF:
            return typed_utterance("/stop", self.name)
        return typed_utterance(str(line).rstrip("\r\n"), self.name)

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

            def run() -> None:
                for raw in iter(stream.readline, ""):
                    loop.call_soon_threadsafe(q.put_nowait, raw)
                loop.call_soon_threadsafe(q.put_nowait, _EOF)

            self._thread = threading.Thread(target=run, name="console-stdin", daemon=True)
            self._thread.start()
        return self._queue

    # ---- Face
    async def show(self, msg: Display) -> None:
        self.shown.append(msg)
        if msg.kind == "listening":  # the prompt itself is the listening indicator on a terminal
            return
        out = self._stdout or sys.stdout
        prefix = {"say": "Leafi", "status": "  ·", "listening": "  ~", "alert": "  !"}[msg.kind]
        try:
            out.write(f"{prefix}: {msg.text}\n" if msg.kind == "say" else f"{prefix} {msg.text}\n")
            out.flush()
        except (UnicodeEncodeError, ValueError):
            out.write(msg.text.encode("ascii", "replace").decode() + "\n")
