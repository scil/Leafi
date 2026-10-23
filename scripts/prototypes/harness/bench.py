"""Plan M2: run libraries §7's scripted flow and measures on both combinations.

    <proto-venv>\\Scripts\\python scripts/prototypes/harness/bench.py            # everything, prints JSON
    ... bench.py child <comb> <kill> <db>   /   ... bench.py restart <comb> <db>   (used by the kill runs)

Nothing speaks and nothing leaves the machine: the Brain is a MockTransport, the Mouth a list.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT)]

import leafi  # noqa: E402,F401 - runs httpx2.alias_httpx() first, as in production

import anthropic  # noqa: E402
import anyio  # noqa: E402
import httpx2  # noqa: E402

import comb1  # noqa: E402
import comb2  # noqa: E402
import common  # noqa: E402
from common import CANARY, MockClaude, Session, Store, terminate  # noqa: E402

COMBS = {"comb1": comb1, "comb2": comb2}
FLOW_SCRIPT = ["The fox ran home.", "It was late and dark.", "The moon was bright.", "fox", "page_turn"]


def client(mock: MockClaude) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key="test-key-not-real", max_retries=0, timeout=10.0, open_telemetry=False,
                                    http_client=anthropic.DefaultAsyncHttpxClient(
                                        transport=httpx2.MockTransport(mock)))


def brain(comb: str, *mocks: MockClaude):
    return COMBS[comb].Brain([(client(m), f"claude-tier-{i}") for i, m in enumerate(mocks)])


async def run(comb: str, s: Session, b, decision_s: float = 5.0) -> str:
    if comb == "comb1":
        return await comb1.run_session(s, b, decision_s)
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    async with AsyncSQLitePersister.from_values(db_path=str(s.store.path), table_name="burr_state") as p:
        await p.initialize()
        return await comb2.run_session(s, b, p, decision_s)


def new_session(db: Path, script=(), autonomy: int = 8, hard_s: float = 60.0) -> Session:
    store = Store(db)
    store.path = db
    return Session(store=store, script=deque(script), autonomy=autonomy, hard_deadline=time.monotonic() + hard_s)


def rows(store: Store, sql: str, args=()) -> list:
    return store.c.execute(sql, args).fetchall()


# ---------------------------------------------------------------- flow steps 1-3


async def flow(comb: str, db: Path) -> dict:
    s = new_session(db, FLOW_SCRIPT)
    mock = MockClaude(plan=deque(["read_listen", "practise_errors", "end"]))
    reason = await run(comb, s, brain(comb, mock))
    acts = rows(s.store, "SELECT kind, status FROM activities ORDER BY id")
    mis = dict((w, (st, r)) for w, st, r in rows(s.store, "SELECT word, status, reason FROM miscues"))
    ok = (acts == [("read_listen", "completed"), ("practise_errors", "page_turned")]
          and mis["fox"] == ("withdrawn", "practice") and mis["dark"] == mis["moon"] == ("unsure", "not_practised"))
    return {"reason": reason, "activities": acts, "miscues": mis, "ok": ok,
            "canary_in_requests": any(CANARY.encode() in r for r in mock.requests)}


# ---------------------------------------------------------------- flow step 4: stop, deadline, lease loss


async def cancel(comb: str, db: Path, event: str) -> dict:
    s = new_session(db, [("event", event, 0.3)])
    mock = MockClaude(plan=deque(["read_listen"]))
    reason = await run(comb, s, brain(comb, mock))
    aid, status = rows(s.store, "SELECT id, status FROM activities ORDER BY id DESC LIMIT 1")[0]
    t_event = s.events[reason]
    after = [t for t, _ in s.spoken if t >= t_event]
    return {"status": status, "event_to_final_ms": round((s.events[f"final:{aid}"] - t_event) * 1000, 1),
            "spoken_after_event": len(after), "ok": status == common.TERMINAL_STATUS[reason]
            and (event != "lease_lost" or not after)}


async def stop_in_brain_call(comb: str, db: Path) -> dict:
    s = new_session(db)
    mock = MockClaude(hang=True)
    t0 = time.monotonic()

    async def stopper() -> None:
        await anyio.sleep(0.3)
        terminate(s, "stop")

    async with anyio.create_task_group() as tg:
        tg.start_soon(stopper)
        reason = await run(comb, s, brain(comb, mock), decision_s=30)
    return {"reason": reason, "stop_to_session_end_ms": round((time.monotonic() - t0 - 0.3) * 1000, 1),
            "ok": reason == "stop"}


# ---------------------------------------------------------------- flow step 5: kill and resume


def child(comb: str, kill: str, db: str) -> None:
    os.environ["PROTO_KILL"] = kill
    asyncio.run(flow(comb, Path(db)))


def restart(comb: str, db: str) -> None:
    store = Store(Path(db))
    stale = common.recover(store)
    s = new_session(Path(db))
    s.id = common.start_session(store)
    common.offer_continue(s)
    out = {"stale": stale}
    if comb == "comb2":
        out.update(asyncio.run(_burr_resume(s, stale)))
    print(json.dumps(out))


async def _burr_resume(s: Session, stale: list[int]) -> dict:
    """What Burr would do on its own: resume the killed app at its next action and run one step."""
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    async with AsyncSQLitePersister.from_values(db_path=str(s.store.path), table_name="burr_state") as p:
        await p.initialize()
        s.script = deque(["dark", "moon"])
        app = await comb2.build_app(s, brain("comb2", MockClaude(plan=deque(["end"]))), p,
                                    resume_app=f"session-{stale[0]}")
        nxt = app.get_next_action()
        before = rows(s.store, "SELECT COUNT(*) FROM practices")[0][0] + rows(s.store, "SELECT COUNT(*) FROM ledger")[0][0]
        s.cycle_id = rows(s.store, "SELECT MAX(id) FROM cycles")[0][0]
        if nxt is not None and nxt.name != "done":
            async with anyio.create_task_group() as s.tg:
                with anyio.CancelScope() as s.scope:
                    try:
                        await app.astep()
                    except Exception as e:
                        return {"burr_resumes_at": nxt.name, "rerun_error": type(e).__name__}
                s.tg.cancel_scope.cancel()
        after = rows(s.store, "SELECT COUNT(*) FROM practices")[0][0] + rows(s.store, "SELECT COUNT(*) FROM ledger")[0][0]
        return {"burr_resumes_at": nxt.name if nxt else None, "rerun_new_rows": after - before}


def kill_runs(comb: str, tmp: Path) -> dict:
    out = {}
    py = sys.executable
    for kill in ("brain_call", "after_effects", "during_practice"):
        db = tmp / f"{comb}-{kill}.db"
        r = subprocess.run([py, __file__, "child", comb, kill, str(db)], capture_output=True, text=True, timeout=60)
        rr = subprocess.run([py, __file__, "restart", comb, str(db)], capture_output=True, text=True, timeout=60)
        store = Store(db)
        dup = lambda t, k: rows(store, f"SELECT COUNT(*) FROM (SELECT {k} FROM {t} GROUP BY {k} HAVING COUNT(*)>1)")[0][0]
        res = {"child_exit": r.returncode, "restart": json.loads(rr.stdout or "{}") if rr.returncode == 0 else rr.stderr[-400:],
               "duplicate_ledger": dup("ledger", "activity_id, item"), "duplicate_miscues": dup("miscues", "activity_id, word"),
               "running_left": rows(store, "SELECT COUNT(*) FROM activities WHERE status='running'")[0][0],
               "open_cycles": rows(store, "SELECT COUNT(*) FROM cycles WHERE status='open'")[0][0],
               "interrupted": rows(store, "SELECT COUNT(*) FROM activities WHERE status='interrupted'")[0][0],
               "prompts": rows(store, "SELECT COUNT(*) FROM prompts")[0][0]}
        res["ok"] = (res["duplicate_ledger"] == res["duplicate_miscues"] == res["running_left"] == res["open_cycles"] == 0
                     and res["prompts"] == 1 and r.returncode != 0)
        out[kill] = res
    return out


# ---------------------------------------------------------------- flow step 6: pause to ask


async def negotiate(comb: str, db: Path) -> dict:
    s = new_session(db, [None, ("skip",)], autonomy=2)
    await run(comb, s, brain(comb, MockClaude(plan=deque(["read_listen"]))))
    asks = sum(1 for _, t in s.spoken if t.startswith("Shall we"))
    started = rows(s.store, "SELECT COUNT(*) FROM activities")[0][0]
    return {"asks": asks, "skips_left": len(s.skips), "activities_started": started,
            "ok": asks == 2 and len(s.skips) == 0 and started == 0}


# ---------------------------------------------------------------- latency, retries, fallback, privacy


async def latency(comb: str, db: Path, n: int = 200) -> dict:
    mod = COMBS[comb]

    async def noop(s, aid):
        return "completed"

    common.ACTIVITIES["noop"] = noop
    mod.MENU = mod.MENU + ("noop",)
    s = new_session(db)
    await run(comb, s, brain(comb, MockClaude(plan=deque(["noop"] * n + ["end"]))))
    starts = [r[0] for r in rows(s.store, "SELECT started FROM activities ORDER BY id")]
    gaps = [(b - a) * 1000 for a, b in zip(starts, starts[1:], strict=False)]
    m = MockClaude(plan=deque(["noop"] * 1000))
    b, raw = brain(comb, m), client(m)
    layer, sdk = [], []
    for _ in range(100):
        t = time.perf_counter()
        await b.decide("open candidates: 0", time.monotonic() + 5)
        layer.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        await raw.messages.create(model="x", max_tokens=16, messages=[{"role": "user", "content": "x"}],
                                  output_config={"format": {"type": "json_schema", "schema": common.DECISION_SCHEMA}})
        sdk.append((time.perf_counter() - t) * 1000)
    q = lambda xs: [round(statistics.median(xs), 2), round(sorted(xs)[int(0.95 * len(xs))], 2)]
    return {"per_decision_ms_p50_p95": q(gaps), "llm_layer_ms_p50_p95": q(layer), "raw_sdk_ms_p50_p95": q(sdk)}


async def retries(comb: str) -> dict:
    one = MockClaude(plan=deque(["end"]), fail=deque([503]))
    d1 = await brain(comb, one).decide("x", time.monotonic() + 10)
    bad = MockClaude(fail=deque([400]))
    await brain(comb, bad).decide("x", time.monotonic() + 10)
    primary, second = MockClaude(fail=deque([500, 500, 500, 500])), MockClaude(plan=deque(["end"]))
    d3 = await brain(comb, primary, second).decide("x", time.monotonic() + 10)
    budget = MockClaude(fail=deque([503]))
    t = time.monotonic()
    await brain(comb, budget).decide("x", time.monotonic() + 0.3)
    return {"503_then_ok_requests": len(one.requests), "503_then_ok_result": d1.activity if d1 else None,
            "400_requests": len(bad.requests), "fallback_primary_requests": len(primary.requests),
            "fallback_secondary_requests": len(second.requests), "fallback_result": d3.activity if d3 else None,
            "budget_0.3s_requests": len(budget.requests), "budget_elapsed_ms": round((time.monotonic() - t) * 1000)}


def no_network_import(comb: str) -> dict:
    code = (f"import sys; sys.path[:0]={[str(HERE), str(ROOT)]!r}; import leafi; from leafi.core import netguard; "
            f"netguard.install(); import {comb}; print('ok')")
    env = dict(os.environ, LEAFI_NO_NETWORK="1")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    return {"ok": r.returncode == 0 and "ok" in r.stdout, "stderr": r.stderr[-300:]}


def code_lines(path: Path) -> int:
    src = path.read_text(encoding="utf-8")
    doc_lines = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and \
                ast.get_docstring(node) and isinstance(node.body[0], ast.Expr):
            doc_lines.update(range(node.body[0].lineno, node.body[0].end_lineno + 1))
    return sum(1 for i, ln in enumerate(src.splitlines(), 1)
               if ln.strip() and not ln.strip().startswith("#") and i not in doc_lines)


def packages() -> dict:
    import importlib.metadata as md

    site = Path(anyio.__file__).parents[1]

    def size(dist: str) -> int:
        files = md.distribution(dist).files or []
        return sum((site / f).stat().st_size for f in files if (site / f).exists())

    c1 = ["tenacity"]
    c2 = ["tenacity", "stamina", "apache-burr", "aiosqlite", "pydantic-ai-slim", "pydantic-graph", "genai-prices",
          "griffelib", "logfire-api"]
    kb = lambda ds: round(sum(size(d) for d in ds) / 1024)
    return {"comb1": {"new_packages": c1, "kb": kb(c1)}, "comb2": {"new_packages": c2, "kb": kb(c2)}}


async def main_async() -> dict:
    out: dict = {"code_lines": {c: code_lines(HERE / f"{c}.py") for c in COMBS}, "packages": packages()}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:  # Windows: SQLite files still open
        tmp = Path(d)
        for comb in COMBS:
            r = out[comb] = {}
            r["flow"] = await flow(comb, tmp / f"{comb}-flow.db")
            r["cancel"] = {ev: await cancel(comb, tmp / f"{comb}-{ev}.db", ev) for ev in ("stop", "deadline", "lease_lost")}
            r["stop_in_brain_call"] = await stop_in_brain_call(comb, tmp / f"{comb}-brainstop.db")
            r["negotiate"] = await negotiate(comb, tmp / f"{comb}-neg.db")
            r["retries"] = await retries(comb)
            r["latency"] = await latency(comb, tmp / f"{comb}-lat.db")
            r["no_network_import"] = no_network_import(comb)
            r["kill"] = kill_runs(comb, tmp)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child(*sys.argv[2:5])
    elif len(sys.argv) > 1 and sys.argv[1] == "restart":
        restart(*sys.argv[2:4])
    else:
        print(json.dumps(asyncio.run(main_async()), indent=1, default=str))
