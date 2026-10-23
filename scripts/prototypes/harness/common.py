"""Shared ground for plan M2's harness prototype (libraries research §7): domain stubs, the session latch
(anyio scope + deadline watcher, identical in both combinations), scripted input, kill points and a mock
Claude server. Not harness code under comparison: `bench.py` counts only comb1.py / comb2.py.

Throwaway: deleted once the Decision log records the choice (plan M2).
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx2

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, started REAL, ended REAL, end_reason TEXT);
CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY, session_id INT, status TEXT, closed_reason TEXT);
CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY, session_id INT, cycle_id INT, kind TEXT,
    status TEXT, decided_by TEXT, started REAL, ended REAL);
CREATE TABLE IF NOT EXISTS miscues(id INTEGER PRIMARY KEY, cycle_id INT, activity_id INT, word TEXT,
    status TEXT, reason TEXT, UNIQUE(activity_id, word));
CREATE TABLE IF NOT EXISTS practices(id INTEGER PRIMARY KEY, miscue_id INT, attempt INT, outcome TEXT,
    UNIQUE(miscue_id, attempt));
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, session_id INT, activity_id INT, item TEXT);
CREATE TABLE IF NOT EXISTS prompts(id INTEGER PRIMARY KEY, session_id INT, text TEXT);
"""
PAGE_A = ["The fox ran home.", "It was late and dark.", "The moon was bright."]
CANDIDATES = ["fox", "dark", "moon"]  # three practice candidates from page A (flow step 1)
TERMINAL_STATUS = {"stop": "stopped", "lease_lost": "lease_lost", "time_up_session": "time_up_session",
                   "internal_error": "internal_error"}
CANARY = "Zephyrine"  # the learner's name: must never appear in a request body


class Store:
    def __init__(self, path: Path) -> None:
        self.c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.c.execute("PRAGMA busy_timeout=250")
        self.c.executescript(SCHEMA)

    @contextlib.contextmanager
    def tx(self):
        self.c.execute("BEGIN IMMEDIATE")
        try:
            yield self.c
        except BaseException:
            self.c.execute("ROLLBACK")
            raise
        self.c.execute("COMMIT")

    def one(self, sql: str, args=()) -> tuple:
        return self.c.execute(sql, args).fetchone()


# ---------------------------------------------------------------- kill points (flow step 5)


def kill_point(name: str) -> None:
    """`TerminateProcess` on Windows (os.kill with SIGTERM): no finally, no atexit, like a power cut."""
    if os.environ.get("PROTO_KILL") == name:
        os.kill(os.getpid(), signal.SIGTERM)


# ---------------------------------------------------------------- session latch (ADR-0017 §1; same in both)


class Terminal(Exception):
    pass


@dataclass
class Session:
    store: Store
    id: int = 0
    terminal: str | None = None
    scope: anyio.CancelScope | None = None
    tg: anyio.abc.TaskGroup | None = None
    hard_deadline: float = float("inf")
    skips: deque = field(default_factory=deque)
    spoken: list[tuple[float, str]] = field(default_factory=list)
    lease_held: bool = True
    cycle_id: int | None = None
    activity_id: int | None = None
    script: deque = field(default_factory=deque)
    events: dict[str, float] = field(default_factory=dict)
    autonomy: int = 8


def terminate(s: Session, reason: str) -> None:
    if s.terminal is None:
        s.terminal = reason
        s.events[reason] = time.monotonic()
        if reason == "lease_lost":
            s.lease_held = False
        if s.scope is not None:
            s.scope.cancel()


def checkpoint(s: Session) -> None:
    if s.terminal:
        raise Terminal(s.terminal)


async def deadline_watcher(s: Session) -> None:
    await anyio.sleep_until(s.hard_deadline)
    terminate(s, "time_up_session")


def spawn(s: Session, fn, *args) -> None:
    async def guarded() -> None:
        try:
            await fn(*args)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            terminate(s, "internal_error")
            raise
    s.tg.start_soon(guarded)


def map_status(s: Session) -> str:
    return TERMINAL_STATUS.get(s.terminal or "internal_error", "internal_error")


def say(s: Session, text: str) -> None:
    if s.lease_held:  # never speak after lease_lost
        s.spoken.append((time.monotonic(), text))


async def listen(s: Session, timeout: float = 8.0):
    """The next scripted input. ("hang",) waits until cancelled; ("event", name, delay) posts a control event
    after `delay` while hanging; ("skip",) posts a skip; None is silence."""
    item = s.script.popleft() if s.script else None
    if isinstance(item, tuple) and item[0] == "event":
        _, name, delay = item
        s.tg.start_soon(_post_later, s, name, delay)
        await anyio.sleep(3600)
    if item == ("hang",):
        await anyio.sleep(3600)
    if item == ("skip",):
        s.skips.append("skip")
        return "skip"
    return item


async def _post_later(s: Session, name: str, delay: float) -> None:
    await anyio.sleep(delay)
    if name in ("stop", "lease_lost"):
        terminate(s, name)
    elif name == "deadline":
        s.hard_deadline = time.monotonic()
        terminate(s, "time_up_session")


def take_skip(s: Session) -> bool:
    if s.skips:
        s.skips.popleft()
        return True
    return False


# ---------------------------------------------------------------- domain stubs (ADR-0013/0017, minimal)


def start_session(store: Store) -> int:
    with store.tx() as c:
        return c.execute("INSERT INTO sessions(started) VALUES (?)", (time.time(),)).lastrowid


def start_activity(s: Session, kind: str, decided_by: str) -> int:
    with s.store.tx() as c:
        if kind == "read_listen" and s.cycle_id is None:
            s.cycle_id = c.execute("INSERT INTO cycles(session_id, status) VALUES (?, 'open')", (s.id,)).lastrowid
        s.activity_id = c.execute(
            "INSERT INTO activities(session_id, cycle_id, kind, status, decided_by, started) "
            "VALUES (?,?,?,?,?,?)", (s.id, s.cycle_id, kind, "running", decided_by, time.time())).lastrowid
    return s.activity_id


def finish_activity(s: Session, aid: int, status: str) -> None:
    with s.store.tx() as c:
        c.execute("UPDATE activities SET status=?, ended=? WHERE id=?", (status, time.time(), aid))
    s.events.setdefault(f"final:{aid}", time.monotonic())


async def read_listen(s: Session, aid: int) -> str:
    """Flow step 1: reads page A, then one transaction writes the three candidates and their ledger rows."""
    for _ in PAGE_A:
        await listen(s)
        checkpoint(s)
    with s.store.tx() as c:  # effects and ledger in one transaction (ADR-0017 §7.2)
        for w in CANDIDATES:
            c.execute("INSERT INTO miscues(cycle_id, activity_id, word, status) VALUES (?,?,?,'candidate')",
                      (s.cycle_id, aid, w))
        c.execute("INSERT INTO ledger(session_id, activity_id, item) VALUES (?,?,'read_listen')", (s.id, aid))
    kill_point("after_effects")  # between the effects commit and the activity-row commit
    return "completed"


async def practise_errors(s: Session, aid: int) -> str:
    """Flow steps 2-3: one attempt per open candidate; a page turn ends the activity, the rest stay owned."""
    for mid, word in s.store.c.execute("SELECT id, word FROM miscues WHERE cycle_id=? AND status='candidate' "
                                       "ORDER BY id", (s.cycle_id,)).fetchall():
        say(s, f"Let's practise: {word}")
        u = await listen(s)
        checkpoint(s)
        if u == "page_turn":
            return "page_turned"
        with s.store.tx() as c:
            c.execute("INSERT INTO practices(miscue_id, attempt, outcome) VALUES (?,1,?)",
                      (mid, "matched" if u == word else "disagreed"))
            c.execute("UPDATE miscues SET status=?, reason=? WHERE id=?",
                      ("withdrawn" if u == word else "unsure", "practice" if u == word else "disagreed", mid))
            c.execute("INSERT INTO ledger(session_id, activity_id, item) VALUES (?,?,?)", (s.id, aid, word))
        kill_point("during_practice")
    return "completed"


ACTIVITIES = {"read_listen": read_listen, "practise_errors": practise_errors}


def finalize(s: Session, reason: str) -> None:
    """ADR-0017 §2 finalize: the open cycle closes and settles what it still owns."""
    with s.store.tx() as c:
        if s.cycle_id is not None:
            c.execute("UPDATE miscues SET status='unsure', reason=? WHERE cycle_id=? AND status='candidate'",
                      ("skipped" if reason == "stop" else "not_practised", s.cycle_id))
            c.execute("UPDATE cycles SET status='closed', closed_reason=? WHERE id=?", (reason, s.cycle_id))
        c.execute("UPDATE sessions SET ended=?, end_reason=? WHERE id=?", (time.time(), reason, s.id))


def deliver(s: Session) -> None:
    say(s, "See you next time!")


def recover(store: Store) -> list[int]:
    """Startup recovery (ADR-0017 §8.5): running → interrupted, open cycles closed, candidates settled."""
    with store.tx() as c:
        stale = [r[0] for r in c.execute("SELECT id FROM sessions WHERE ended IS NULL")]
        c.execute("UPDATE activities SET status='interrupted', ended=? WHERE status='running'", (time.time(),))
        c.execute("UPDATE miscues SET status='unsure', reason='interrupted' WHERE status='candidate' AND cycle_id "
                  "IN (SELECT id FROM cycles WHERE status='open')")
        c.execute("UPDATE cycles SET status='closed', closed_reason='interrupted' WHERE status='open'")
        c.execute("UPDATE sessions SET ended=?, end_reason='interrupted' WHERE ended IS NULL", (time.time(),))
    return stale


def offer_continue(s: Session) -> None:
    with s.store.tx() as c:
        c.execute("INSERT INTO prompts(session_id, text) VALUES (?, 'continue from page A?')", (s.id,))
    say(s, "Continue from page A?")


# ---------------------------------------------------------------- mock Claude (a MockTransport, no socket)

DECISION_SCHEMA = {"type": "object", "properties": {"activity": {"type": "string"}, "reason": {"type": "string"}},
                   "required": ["activity", "reason"], "additionalProperties": False}


@dataclass
class MockClaude:
    """Answers both shapes: structured output as text JSON (raw SDK) or a tool call (pydantic-ai's output tool).
    `plan` is the sequence of activities the Brain picks; `fail` a list of status codes to return first."""
    plan: deque = field(default_factory=deque)
    fail: deque = field(default_factory=deque)
    requests: list[bytes] = field(default_factory=list)
    hang: bool = False

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = await request.aread()
        self.requests.append(body)
        kill_point("brain_call")
        if self.hang:
            await anyio.sleep(3600)
        if self.fail:
            code = self.fail.popleft()
            return httpx2.Response(code, json={"type": "error", "error": {"type": "api_error", "message": "x"}})
        req = json.loads(body)
        choice = {"activity": self.plan.popleft() if self.plan else "end", "reason": "mock"}
        if req.get("tools"):
            content = [{"type": "tool_use", "id": "toolu_1", "name": req["tools"][0]["name"], "input": choice}]
            stop = "tool_use"
        else:
            content = [{"type": "text", "text": json.dumps(choice)}]
            stop = "end_turn"
        return httpx2.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant",
                                          "model": req["model"], "content": content, "stop_reason": stop,
                                          "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 5}})


def observation(s: Session) -> str:
    """What the Brain sees: counts and kinds only, never the learner's name (the canary checks this)."""
    open_ = s.store.one("SELECT COUNT(*) FROM miscues WHERE cycle_id=? AND status='candidate'", (s.cycle_id,))[0]
    return f"open candidates: {open_}; menu: read_listen, practise_errors, end"
