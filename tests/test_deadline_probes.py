"""Deadlines and cancellation on the app's asyncio loop with anyio scopes (ADR-0017 §1; plan M2; probes P-A1-P-A7
of `docs/research/2026-10-22-harness-libraries.md` §2). Nothing leaves the machine: hung servers listen on
127.0.0.1. Timings are generous upper bounds for a loaded Windows CI box, not the measured values (those are
printed by `scripts/prototypes/harness/bench.py`)."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import threading
import time

import anthropic
import anyio
import pytest

LATE_S = 0.25  # how late a cancellation may land on this box (Windows timer ~15.6 ms)


@contextlib.asynccontextmanager
async def _hung_server():
    """Accepts and reads, answers nothing unless the request asks for it (`/ok`). Yields the port. On exit the
    connections are aborted: 3.12's `Server.wait_closed` waits for every open connection."""
    writers: list[asyncio.StreamWriter] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                length = next((int(h.split(b":")[1]) for h in head.split(b"\r\n")
                               if h.lower().startswith(b"content-length:")), 0)
                await reader.readexactly(length)
                if b" /ok/" in head.split(b"\r\n")[0] or b"/ok/v1" in head:
                    body = (b'{"id":"m","type":"message","role":"assistant","model":"x","content":[{"type":"text",'
                            b'"text":"ok"}],"stop_reason":"end_turn","stop_sequence":null,'
                            b'"usage":{"input_tokens":1,"output_tokens":1}}')
                    writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
                                 + str(len(body)).encode() + b"\r\n\r\n" + body)
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        for w in writers:
            w.transport.abort()
        server.close()
        with anyio.move_on_after(2):
            await server.wait_closed()


def _client(port: int, path: str = "") -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=f"http://127.0.0.1:{port}{path}",
                                    max_retries=0, timeout=30.0, open_telemetry=False)


async def _ask(client: anthropic.AsyncAnthropic):
    return await client.messages.create(model="claude-opus-5-5", max_tokens=16,
                                        messages=[{"role": "user", "content": "hi"}])


async def test_p_a1_a_deadline_cancels_a_hung_sdk_request_a_sleep_and_a_child():
    stopped: dict[str, float] = {}

    async def child() -> None:
        try:
            await anyio.sleep(30)
        finally:
            stopped["child"] = time.monotonic()

    async with _hung_server() as port:
        client = _client(port)
        t0 = time.monotonic()
        with anyio.move_on_after(0.3) as scope:
            async with anyio.create_task_group() as tg:
                tg.start_soon(child)
                try:
                    await _ask(client)
                finally:
                    stopped["request"] = time.monotonic()
        assert scope.cancelled_caught
        late = {name: t - t0 - 0.3 for name, t in stopped.items()}
        t1 = time.monotonic()
        with anyio.move_on_after(0.3):
            await anyio.sleep(30)
        late["sleep"] = time.monotonic() - t1 - 0.3
        assert set(late) == {"child", "request", "sleep"}
        assert all(v < LATE_S for v in late.values()), late
        await client.close()


async def test_p_a2_a_bare_create_task_child_is_not_cancelled_by_the_scope():
    done = asyncio.Event()

    async def bare() -> None:
        await asyncio.sleep(0.2)
        done.set()

    with anyio.move_on_after(0.05):
        task = asyncio.create_task(bare())
        await anyio.sleep(1)
    await asyncio.wait_for(done.wait(), 1)  # outlived the scope: spawn only through a TaskGroup (ADR-0017 §1)
    assert task.done() and not task.cancelled()


async def test_p_a3_shielded_cleanup_runs_after_the_deadline_and_is_cut_at_its_own_budget():
    ran: list[str] = []

    async def hung_tts() -> None:
        await anyio.sleep(30)

    t0 = time.monotonic()
    with anyio.move_on_after(0.1):
        try:
            await anyio.sleep(30)
        finally:
            with anyio.move_on_after(0.3, shield=True):
                ran.append("cleanup")
                await hung_tts()
            ran.append("after")
    elapsed = time.monotonic() - t0
    assert ran == ["cleanup", "after"]
    assert 0.4 - 0.05 < elapsed < 0.4 + LATE_S


async def test_p_a4_a_latch_cancel_mid_decision_takes_the_same_cleanup_path_with_its_reason():
    seen: list[str] = []
    terminal: list[str] = []

    async def decision(scope: anyio.CancelScope) -> None:
        try:
            await anyio.sleep(30)
        except anyio.get_cancelled_exc_class():
            seen.append(terminal[0])  # the latch is set before the scope is cancelled
            raise

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as tg:
            tg.start_soon(decision, scope)
            await anyio.sleep(0.05)
            terminal.append("stop")
            scope.cancel(reason="parent_stop")
    assert scope.cancelled_caught and seen == ["stop"]


async def test_p_a5_a_library_swallowing_cancellation_once_is_cancelled_again_at_its_next_await():
    awaits: list[str] = []

    async def rude_library() -> None:
        try:
            await anyio.sleep(30)
        except BaseException:  # swallows CancelledError once, like some libraries do
            awaits.append("swallowed")
        await anyio.sleep(30)  # level-triggered: raised again here
        awaits.append("ran past")

    t0 = time.monotonic()
    with anyio.move_on_after(0.1) as scope:
        await rude_library()
    assert scope.cancelled_caught and awaits == ["swallowed"]
    assert time.monotonic() - t0 < 0.1 + LATE_S


def test_p_a6_abandoned_thread_neither_delays_the_caller_nor_blocks_process_exit(tmp_path):
    code = r"""
import time, threading, anyio
stop = threading.Event()
def blocking():
    while not stop.wait(0.05):   # cooperative stop flag: threads cannot be cancelled
        pass
async def main():
    t0 = time.monotonic()
    with anyio.move_on_after(0.2):
        try:
            await anyio.to_thread.run_sync(blocking, abandon_on_cancel=True)
        finally:
            stop.set()
    print(round(time.monotonic() - t0, 3))
anyio.run(main)
"""
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    total = time.monotonic() - t0
    assert r.returncode == 0, r.stderr
    assert float(r.stdout.strip()) < 0.2 + LATE_S
    assert total < 10  # interpreter start included; a blocked exit would hang for the thread


async def test_p_a7_the_client_still_works_after_50_deadline_cancelled_requests():
    async with _hung_server() as port:
        hung = _client(port)
        for _ in range(50):
            with anyio.move_on_after(0.02):
                await _ask(hung)
        ok = hung.with_options(base_url=f"http://127.0.0.1:{port}/ok")
        with anyio.fail_after(5):
            msg = await _ask(ok)  # a PoolTimeout or a hang here is the httpcore leak (libraries §2)
        assert msg.content[0].text == "ok"
        await hung.close()


@pytest.fixture(autouse=True)
def _no_stray_threads():
    before = threading.active_count()
    yield
    assert threading.active_count() <= before + 2
