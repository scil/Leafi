# Harness libraries: what to build the study harness's generic machinery on (reference collection)

Checked: 2026-10-22. Method: `tiered-research` (T1 = the owner's own docs, PyPI metadata, the project's repository; T2 = empirical studies; T3 = exemplar source files or local measurements read directly; T4 = secondary, "reported" only). Six parallel searches, one per mechanism; every claim below traces to a row of §9. Rows marked *(inferred)* or *(not verified)* were not confirmed against a primary source.

Decision it serves: ADR-0017 (AI-led study session) and ADR-0018 (learners and privacy v2) were drafted with hand-written infrastructure, and the second code-plan review (2026-10-22) found that hand-written migrations, grants and retries keep producing defects. The owner asked to base generic machinery on mature open-source libraries, to research alternatives for every candidate, and (2026-10-22, second message) allowed **using only part of a library**. Domain logic (alignment, practice rules, menu policy, privacy rules) stays Leafi's own.

Hard constraints every candidate is checked against:

- Leafi's code owns half-duplex mic gating and turn timing.
- Every request is filtered for privacy before it leaves the machine (ADR-0011, ADR-0018).
- Local models (Ollama) and the loopback gateway magpie (127.0.0.1:3425, OpenAI-compatible) work.
- Structured (typed) outputs.
- A few seconds per decision on the voice path.
- Windows 11 without Docker for the core loop; Python 3.12; small enough to live in one process.

## 0. Findings that cut across mechanisms

1. **The Python LLM ecosystem split into `httpx` and `httpx2` in August 2026.** `httpx2` is Pydantic's continuation of HTTPX (L14, E15). `anthropic` ≥ 1.0.0 (2026-08-20) and `openai` ≥ 3.0.0 (2026-08-12) depend on `httpx2` and reject `httpx` clients with a `TypeError` (L15, L17, E10–E12). pydantic-ai-slim moved in 2.32.0 (L1, L2); `huggingface_hub` 2.x moved, `ollama` 0.6.3 did not (E17, E41, E42). Leafi pins `anthropic==0.120.2` on `httpx` 0.28.1 (TD-1, L46). Anything that hooks the HTTP layer (egress transport, retries, test mocks) must be written for both families, or Leafi runs `httpx2.alias_httpx()` before any `httpx` import (E11, E13). This makes TD-1 a precondition for adopting current library versions, not just a nice-to-have.
2. **Every Stainless-generated SDK retries twice by default and times out after 10 minutes** (R19, R21, L16, L18). Any app-level retry, fallback or egress refusal stacks on that unless the SDK is built with `max_retries=0` and a per-request timeout.
3. **No framework examined cancels a running step mid-way at an external event.** LangGraph checkpoints at step boundaries (O5), DBOS cancels "at the beginning of its next step" (O27), and Burr and pydantic-graph do not document mid-action cancellation (O15, O20). Cancellation at any await is a property Leafi gets from cancel scopes (§2), whatever the orchestrator.
4. **Threads cannot be cancelled** (D4, D11). Blocking ASR/TTS run through `to_thread` keeps running after a deadline; only a cooperative stop flag or the engine's own abort stops it.

## 1. SQLite schema migrations

Need:

- Migrations run only from an explicit command, never on open.
- Table rebuilds for changed CHECK, UNIQUE or NOT NULL constraints.
- Safe while the supervisor holds the file open on Windows.
- Plain `sqlite3`, no ORM forced.
- Detects "the database is behind" without applying anything.

Local facts:

- SQLite in the venv is **3.49.1** (M32).
- `storage.py` has `ON DELETE CASCADE` foreign keys on four child tables, sets `foreign_keys=ON` and `busy_timeout=5000`, and uses the rollback journal, not WAL (M33).

| Candidate | License | Latest (date) | Maintenance | Win / 3.12 | Weight | Rebuild for constraint changes | No ORM | Lock with a 2nd process | Pending check | Partial use |
|---|---|---|---|---|---|---|---|---|---|---|
| **Alembic** batch mode | MIT (M1) | 1.20.1 (2026-10-22) (M1) | commit 2026-10-22; monthly releases (M1, M2) | OS-independent; 3.10–3.15 (M1) | SQLAlchemy ≥ 2.0 (2.1.6 needs py ≥ 3.11), Mako, typing-extensions (M1, M9) | Move-and-copy, recreates reflected indexes (M3, M4). **Unnamed CHECKs dropped** (warning since 1.20). **Caller must turn `foreign_keys` off**; referencing FKs and triggers are not handled (M3, M4) | Yes: standalone `Operations(MigrationContext.configure(conn))` (M6) | No migration lock; `transactional_ddl=False` on SQLite (M5); pysqlite autocommits DDL unless `autocommit=False` (M8) | `current --check-heads` (M7) | `Operations.batch_alter_table` alone under Leafi's own runner, imported only by the migrate command |
| **sqlite-utils** `transform()` / `transform_sql()` | Apache-2.0 (M10) | 4.2.1 (2026-08-13) (M10) | commit 2026-10-11 (M11) | py 3.10–3.14; Windows not stated (M10) | click, pluggy, dateutil, tabulate, sqlite-fts4, **pip** (M10) | New table, copy, drop, rename. Keeps existing CHECK and UNIQUE and recreates indexes. Sets `legacy_alter_table=ON`, turns FKs off and runs `foreign_key_check` (M12, M13). **No parameter to add or change a CHECK or UNIQUE** (M12, M13). Triggers not recreated (M13) | Yes, takes a `sqlite3.Connection` (M13) | `atomic()` uses deferred `BEGIN` (M13) | `Migrations.pending()` (M14) | `transform_sql()` as a rebuild generator, but Leafi's failing case (CHECK/UNIQUE change) is exactly what it cannot express |
| sqlite-migrate | Apache-2.0 | 0.2 (2026-07-07) | **archived**, merged into sqlite-utils 4 (M15) | — | — | as sqlite-utils | — | — | — | — |
| yoyo-migrations | Apache (M16) | 9.0.0 (**2024-08-10**) | no release in 2 years (M16) | not stated | sqlparse, tabulate | none (M17) | yes | `yoyo_lock` table (M17) | `yoyo list` (M17) | runner only; Leafi already has one |
| **Atlas** (Go binary) | Community build Apache-2.0 (M18) | v1.3.0 (2026-08-02) (M22) | commit 2026-10-21 (M22) | Windows exe (M18) | one binary | Declarative diff, `new_X` rebuild (M20). FK pragma placed inside the default per-file transaction, where it is a no-op; no `foreign_key_check` (M19, M20). Triggers and lint are paid-tier (M18) | yes | advisory lock (M19) | `migrate status` (M19) | dev-time diff only ("fresh vs migrated schema"), never at runtime |
| dbmate | MIT | v2.37.0 (2026-10-18) (M23) | active | scoop | binary | none | yes | lock is PostgreSQL only (M23) | `status` | — |
| peewee `SqliteMigrator` | MIT (M24) | 4.5.3 (2026-10-07) | active | — | peewee | Regex-parsed rebuild. **`add_constraint`, `add_unique` raise `NotImplementedError` on SQLite** (M24) | yes | none | — | not worth it |
| caribou | Unlicense (M26) | 0.6.0 (2026-02-06) | commit 2026-05-10 (M34) | py 3.10–3.14 | **zero deps** | none | yes | none | not documented | — |
| pyway | **GPL-3.0** (M27) | 0.3.33 (2026-07-23) | 21-month release gap | — | psycopg2, mysql-connector, duckdb (M27) | none | yes | — | `info` | — |
| SQLite ≥ 3.53 native `ALTER` | public domain | 3.53.0 (2026-04-09) (M29) | — | — | — | Adds and removes NOT NULL and CHECK natively (M28, M29). **Not available: venv has 3.49.1** (M32) | — | — | — | — |

Constraint fit:

- No candidate meets all constraints.
- sqlite-utils cannot change CHECK or UNIQUE.
- Alembic is heavy and leaves foreign keys and triggers to the caller.
- The runner-only tools (yoyo, dbmate, caribou, pyway) do no rebuilds.
- Atlas's SQLite plans need hand review.
- None provides a SQLite-specific exclusive lock; Leafi takes it itself.

Pitfalls:

- **CASCADE data loss.** Dropping a parent table with `foreign_keys=ON` deletes its children. The pragma is a no-op inside a transaction, so it must be set before `BEGIN` (M13, M28). Leafi has four CASCADE children (M33).
- **Rename order.** Rename the *new* table into place; renaming the old one first corrupts references (M28).
- **Lost triggers and unnamed CHECKs** (M3, M4, M13).
- **DDL autocommit in the Python driver.** `executescript` commits a pending transaction first, and DDL autocommits under the legacy transaction mode (M8, M31).
- **`COMMIT` can return SQLITE_BUSY in rollback-journal mode while another process reads** (M30).

**Recommendation.**

- Keep Leafi's `user_version` runner, but run it only from `python -m leafi db migrate`.
- `open()` refuses to start when the version differs.
- Replace hand-written rebuilds with **one generic `rebuild(table, target_create_sql)` helper** that follows SQLite's 12-step procedure (M28) with sqlite-utils' safeguards copied (M13), in this order:
  1. Set `foreign_keys=OFF` before the transaction.
  2. `BEGIN IMMEDIATE`.
  3. Capture index and trigger SQL.
  4. Create `new_X` from the full target DDL.
  5. Copy the shared columns.
  6. Drop the old table, then rename `new_X` under `legacy_alter_table=ON`.
  7. Recreate indexes and triggers.
  8. Run `foreign_key_check`.
  9. Set `user_version`, `COMMIT`, then turn foreign keys back on.
- Add a test that the migrated `sqlite_schema` equals a freshly created one.

Trade-off: about 80 lines Leafi owns and no new dependency, against the edge cases sqlite-utils already handles. Fallback if the helper proves fragile: Alembic's `Operations.batch_alter_table` alone, only in the migrate command. It costs SQLAlchemy and Mako, every constraint must be named, and Leafi still handles foreign keys.

Prototype must test:

1. Change a CHECK, add a UNIQUE and set NOT NULL on `page_reads` with CASCADE children present. Child row counts must be unchanged and `foreign_key_check` empty. Run once more with FKs left on, to prove the test catches CASCADE loss.
2. Partial and expression indexes, `sqlite_sequence` and triggers survive; the migrated schema equals a fresh one.
3. On Windows, with the supervisor holding a read and then a write transaction, `BEGIN IMMEDIATE` fails cleanly within a short timeout. Repeat for `COMMIT` hitting BUSY. The supervisor's long-lived connection keeps working after the schema change.
4. A step with a violated CHECK rolls back fully, leaving `user_version` and the FK pragma restored.
5. `open()` on a database one version behind refuses to start and writes nothing.

## 2. Deadlines and cancellation

Need:

- One absolute session deadline caps every await.
- At the deadline, everything is cancelled: child tasks, in-flight HTTP, playback.
- Cleanup runs with its own short budget.
- Each decision can have a nested, shorter deadline.
- The control latch can cancel from outside.

| Candidate | License | Latest (date) | Maintenance | Win / 3.12 | Semantics | Weight | Partial use |
|---|---|---|---|---|---|---|---|
| **anyio** cancel scopes | MIT (D1) | 4.15.1 (2026-09-05); installed 4.14.2 (D1) | 5 releases Jun–Sep 2026 (D1) | pure Python, ≥ 3.10 (D1) | **Level-triggered**: re-raised at every await inside a cancelled scope (D2). `CancelScope(deadline=…)`, nested `move_on_after`/`fail_after`, `current_effective_deadline()`, `cancel(reason=)` (4.11), `TaskGroup.cancel()` (4.14), `move_on_at`/`fail_at` (4.15) (D3, D5) | already installed; idna, typing_extensions | `CancelScope` + anyio `TaskGroup` + `to_thread.run_sync(abandon_on_cancel=True)` inside the existing `asyncio.run` app (*inferred*, prototype P-A1) |
| stdlib asyncio `timeout_at` + `TaskGroup` | PSF | 3.12 | CPython | native; Proactor default (D12) | **Edge-triggered**: raised once, can be swallowed; code that suppresses it must call `uncancel()` (D7). No shield scope, only `asyncio.shield()` on a separate task (D7, D13) | none | `timeout_at` + `Timeout.reschedule()` alone (D7) |
| trio | MIT/Apache-2.0 (D14) | 0.34.0 (2026-08-11) | active | ≥ 3.10 | origin of cancel scopes; caller-owned deadlines; shielded, bounded cleanup (D15) | second runtime | design rules only |
| quattro | Apache-2.0 (D16) | 26.1.0 (2026-03-31) | single maintainer, commit 2026-09-30 (D17) | ≥ 3.10 | asyncio-native `fail_at`/`move_on_at`, TaskGroup subclass (D16) | attrs | duplicates anyio |
| aiotools | MIT (D18) | 2.2.4 (2026-07-21) | active | ≥ 3.11 | `ShieldScope`, `VirtualClock` for tests (D18) | async-lru | `VirtualClock` as a test aid only |
| async-timeout | Apache-2 | 5.0.1 (2024-11-06) | **deprecated**, upstreamed into 3.11 (D19) | — | — | — | do not use |

Constraint fit:

- **Cleanup budget.** anyio's documented pattern runs cleanup inside `move_on_after(N, shield=True)` (D2).
- **SDK retry loop.** It catches `Exception` only, so `CancelledError` passes straight through it (R20).
- **Windows clock.** About 15.6 ms resolution and no `add_signal_handler`. Neither matters for budgets in seconds (D12, *inferred*).
- **Pause.** Should be a state the session waits on, not a cancellation (*inferred*).

Pitfalls:

- **Python 3.12 TaskGroup can lose a parent cancellation** when a child fails at the same moment. Fixed only in 3.13 (D7, D9).
- **anyio shields do not block a raw `task.cancel()`** (D6). Do not mix raw cancels with shields.
- **Scope ordering.** Scopes must be exited LIFO in the same task; never hold one across an async-generator `yield` (D2).
- **Bare `asyncio.create_task` children** are outside anyio's level semantics (D2). Spawn children through an anyio `TaskGroup`.
- **httpcore pool leak.** A request cancelled while still connecting can leak a pool slot and cause later `PoolTimeout`. PR #1099 is still open; httpcore 1.0.9 is from 2025-04 (D20, D21). A long-lived process must be able to rebuild its client.
- **`move_on_after` starts its timer when called, not when entered** (D3).

**Recommendation.** Adopt anyio partially, on the existing asyncio loop, with no `anyio.run` and no new package:

- The session runs under `CancelScope(deadline=t0+session_s)`; each decision runs in a nested `move_on_after` or `fail_after`.
- Children are spawned only through an anyio `TaskGroup`.
- The latch calls `scope.cancel(reason="parent_stop")`.
- In `finally`, cleanup (stop audio, say goodbye, write final state) runs in a shielded scope with its own `move_on_after(goodbye_s)`.
- Thread work uses `abandon_on_cancel=True` plus a cooperative stop flag.

Optionally upgrade to anyio ≥ 4.15.1 for `move_on_at` (D5). Trade-off: a rule to never mix raw `task.cancel()` or `asyncio.timeout` around shielded code, against plain asyncio's missing shield scope and its 3.12 TaskGroup bug.

Prototype must test:

- **P-A1.** On Windows Proactor, a deadline cancels a hung `AsyncAnthropic` request, an `anyio.sleep` and a TaskGroup child. Measure how late each stops.
- **P-A2.** A bare `create_task` child is *not* cancelled (confirms the spawning rule).
- **P-A3.** A shielded 2 s cleanup runs after the deadline and is itself cut off at 2 s when TTS hangs.
- **P-A4.** A latch cancel mid-decision takes the same cleanup path, with its reason visible.
- **P-A5.** A fake library that swallows `CancelledError` once is cancelled again at its next await.
- **P-A6.** With `abandon_on_cancel`, the caller returns on time and process exit is not blocked by the thread (D10).
- **P-A7.** After 50 deadline-cancelled requests, the client still works without `PoolTimeout`.

## 3. Retries with backoff and a single retry owner

| Candidate | License | Latest (date) | Maintenance | Async | Weight | Notes | Partial use |
|---|---|---|---|---|---|---|---|
| **tenacity** | Apache-2.0 (R1) | 9.2.1 (2026-10-07) | commit 2026-10-12 (R2) | `AsyncRetrying` (R3) | **no runtime deps** (R1) | `stop_after_delay` / `stop_before_delay` count from the first attempt, not to an absolute deadline (R5) | only the wait strategies (`wait_exponential_jitter`) and a custom stop callable inside Leafi's own loop (R4, R5) |
| **stamina** | MIT (R6) | 26.1.0 (2026-04-13) | commit 2026-10-19 (R7) | `AsyncRetryingCaller` (R8) | tenacity | Defaults `attempts=10`, `timeout=45` (relative) (R8). An `on=` hook may return a float delay, but that bypasses its clamping (R8, R9). `set_testing()` for tests (R8). Default hooks see call args (R8) | `AsyncRetryingCaller` built per call with `timeout=deadline-now` |
| backoff | MIT (R10) | 2.2.1 (**2022-10-05**) | last commit 2023-01-20 (R11) | yes (R12) | none | looks unmaintained | do not use |
| httpx `HTTPTransport(retries=)` | BSD-3 | 0.28.1 | — | — | built in | retries only `ConnectError`/`ConnectTimeout` (R13) | — |
| httpx-retries | MIT (R14) | 0.6.0 (2026-07-06) | — | yes | httpx | default methods **exclude POST**; Retry-After capped at 120 s (R15); cannot retry body-read errors (R14); not usable with `httpx2` | — |
| aiohttp-retry | MIT (R16) | 2.9.1 (2024-11-06) | commit 2026-04-08 (R17) | aiohttp only | aiohttp | not applicable | — |
| **SDK `max_retries`** (anthropic 0.120.2) | — (R18) | installed 0.120.2 | active | built in | — | Default 2 retries on connect errors, 408, 409, 429, ≥ 500 (R19). Honours `x-should-retry`; Retry-After only if 0 < value ≤ 60 s; backoff 0.5 → 8 s with jitter (R20, R21). Timeout 600 s, connect 5 s (R21) | its error classes as the retry classifier; set `max_retries=0` |
| pydantic-ai retries | MIT (R22) | 2.59.0 (2026-10-21) | active | tenacity transport (R23) | the framework | its own docs warn that SDK and transport retries multiply (one example: 18 requests) (R23) | — |

Constraint fit and pitfalls:

- A **single retry owner** means `max_retries=0` on every SDK client (R19) and no transport retries.
- **No library knows an absolute deadline** (R5, R9). Leafi gives up when `now + upcoming_sleep + min_attempt ≥ deadline`, and the surrounding cancel scope (§2) interrupts an attempt already in flight.
- The SDK ignores a Retry-After above 60 s (R20); Leafi should give up instead of sleeping.
- `anthropic` 2.x uses `httpx2` (R19), so retries tied to the `httpx` transport would break on upgrade.

**Recommendation.** Leafi's own retry loop is the only retrier.

- **Smallest option:** about 30 lines that use tenacity's wait objects for timing (no runtime deps), check against the absolute deadline, and classify errors by the SDK's own exception classes (`APIConnectionError`, `RateLimitError`, `InternalServerError`, 408, 409, `x-should-retry`).
- **Alternative:** stamina's per-call `AsyncRetryingCaller` with `attempts=2–3` and `timeout=deadline-now`, which buys `set_testing()`.

Trade-off: stamina is less code with a good test switch, but its deadline is relative and a custom backoff is unclamped. The hand-written loop is explicit about the absolute deadline. Either way, give up early enough to leave time for a fallback line.

Prototype must test:

- **P-B1.** With `max_retries=0`, exactly N requests reach a fake 503 server (no stacking).
- **P-B2.** A Retry-After of 30 s with 5 s of budget left gives up immediately, with a distinct "budget exhausted" error.
- **P-B3.** The classifier retries connect errors, 408, 409, 429 and ≥ 500, and does not retry 400, 401, 403 or `x-should-retry: false`.
- **P-B4.** A deadline arriving during a backoff sleep propagates as cancellation, not as another retry.
- **P-B5.** Tests run with no real sleeps.
- **P-B6.** P-B1 passes again on anthropic 2.x before any upgrade.

## 4. Session orchestration

Need:

- The Brain chooses the next activity from a code-computed menu; code executes it.
- State is persisted per step and resumes after a crash.
- The session can pause to ask the learner.
- External events (page turn, stop latch, deadline) interrupt mid-activity.

| Candidate | License | Latest (date) | Maintenance | Weight | Persistence (own SQLite?) | Pause / resume | Cancel a running node | Owns LLM layer? | Telemetry | Partial use |
|---|---|---|---|---|---|---|---|---|---|---|
| **LangGraph** | MIT (O1) | 1.2.16 (2026-10-16) | commit 2026-10-21 (O7) | langchain-core (with langsmith, tenacity, httpx), checkpoint, prebuilt, sdk, xxhash (O1, O3) | `AsyncSqliteSaver(aiosqlite.Connection)` takes the app's connection. Docs: "not recommended for production". The saver package pulls **sqlite-vec** (O2, O6) | `interrupt()` + `Command(resume=)`. **The whole node re-runs from its first line on resume**; resume values match by position (O4). Durability `exit`/`async`/`sync` (O5) | only at step boundaries (O5); outer cancel ends the run with no cleanup node (*reported*, T4-1) | no (O4) | LangSmith opt-in (O8), but `langsmith` is always installed (O3) | saver alone under a hand loop; its opaque checkpoint blobs become a second source of truth beside Leafi's tables |
| **Pipecat Flows** | BSD-2 (O9) | 1.4.0 (2026-07-05), **deprecated**, now `pipecat.flows` in pipecat-ai ≥ 1.5 (O9, O10) | follows pipecat-ai | all of pipecat-ai: numpy, numba, onnxruntime, soxr, openai, aiohttp… (O13) | none: `FlowManager.state` is a dict (O11) | node rewrites LLM context and tools (O12) | via pipeline frames | **yes**: requires a Pipecat `LLMService` and context aggregator, and assumes its STT→LLM→TTS pipeline (O11, O12) | not checked | only the idea (node = prompt + allowed functions + transitions); ADR-0017's menu already expresses it |
| **pydantic-graph** | MIT (O14) | 2.59.0 (2026-10-21) | commit 2026-10-22 (O16) | anyio, logfire-api, pydantic, typing-inspection; no pydantic-ai (O14) | **none: persistence removed in V2** (O15) | `graph.iter()` drives steps by hand (O15) | not documented | no | logfire-api installed; export default *not verified* | typed dispatch table only |
| **Burr** (Apache incubating) | Apache-2.0 (O17) | 0.43.0 (2026-08-25) | commit 2026-10-19 (O23) | **no core deps**; extras only (O17) | `AsyncSQLitePersister(connection, table_name)` on the app's connection; state written after every action; `initialize_from(resume_at_next_action=)` (O18, O19) | `halt_before`/`halt_after`, then `step(inputs=)` (O20) | not documented (O20) | no | usage telemetry **removed** in 0.43.0 (O22); tracker opt-in, writes `~/.burr` (O21) | persister alone, or `Application` with Leafi's `checkpoint()` inside actions |
| **DBOS Transact** | MIT (O24) | 3.3.0 (2026-10-15) | commit 2026-10-20 (O30) | psycopg[binary] even for SQLite, sqlalchemy, croniter, click (O24) | system database, SQLite by default; Postgres recommended; notifications poll on SQLite (O25) | durable `recv` with timeout (O28); workflows must be deterministic (O26) | at the next step unless the step is `preemptible` (O27) | no | OTLP off; Conductor only with a key (O29); Windows *not stated* (O25) | not separable from its system database |
| Temporal | MIT (O31) | 1.34.0 (2026-09-30) | active | native core | **needs a server** (O31) | signals | server side | no | — | — |
| **python-statemachine** | MIT (O32) | 3.2.2 (2026-10-14) | commit 2026-10-16 (O34) | **no core deps** (O32) | state lives on a model the app persists (O33) | — | — | no | none found | the `ActivityStatus` lifecycle only |
| transitions | MIT (O35) | 0.9.3 (2025-07-02) | commit 2025-09-09, slow (O36) | six | app-persisted | — | — | no | none found | — |
| LlamaIndex Workflows | MIT (O37) | 2.26.1 (2026-10-21) | active | instrumentation, pydantic | serialize/resume claimed (O37); `Context.to_dict` *reported* (T4-2) | *not verified* | *not verified* | no | not checked | — |
| Restate / Hatchet / Prefect | — | restate-sdk 1.1.0; hatchet-sdk 1.42.1; prefect 3.9.0 (O38–O40) | — | each needs its own server or engine; Prefect has 57 core deps (O39) | — | — | — | — | — | out of scope |
| **Hand-written loop** (ADR-0017 §2) | own | — | — | 0 | Leafi's own `activities`/`cycles`/ledger tables, effects and ledger in one transaction (ADR-0017 §7.2) | `listen()` awaits in-process; after a crash the activity is marked `interrupted` and the learner is asked "continue from page N?" (§8.5) | `checkpoint()` after every await + latch + deadline (§1) | no | none | — |

Constraint fit:

- **Fails the hard constraints:** Pipecat Flows (owns the LLM layer and needs Pipecat's pipeline), Temporal, Restate, Hatchet and Prefect (server).
- **Passes with caveats:**
  - LangGraph: heavier; its node re-run conflicts with side-effecting nodes; the sqlite-vec wheel on Windows is *not verified*.
  - Burr: light; documents no mid-action cancel.
  - pydantic-graph: a step driver only, with no persistence.
  - DBOS: brings psycopg and has no Windows statement.

Pitfalls:

- **LangGraph** re-runs a node on resume, so speaking or ledger writes before `interrupt()` happen twice (O4). Its `async` durability can lose the last checkpoint (O5). An unclosed `AsyncSqliteSaver` can hang the program (O6).
- **Pipecat Flows** as a standalone package is frozen (O9).
- **pydantic-graph** tutorials that show `FileStatePersistence` are obsolete (O15).
- **Burr** gives `inputs` only to the first action of `run`/`iterate` (O20).
- **DBOS** raises a nondeterminism error when a replay sees different step results (O26).
- **Any framework's checkpoint table** is an extra writer in a database the supervisor holds (*inferred*: `SQLITE_BUSY` risk).

**Recommendation.** Keep the hand-written loop ADR-0017 §2 specifies; take no orchestration framework.

- The hard parts are Leafi-specific: epoch check, monotonic latch, one deadline on every await, single-use skips, `Reobserve`. No framework cancels mid-step (finding 0.3).
- A paused spoken question to a child should not survive a crash as a frozen node. ADR-0017 §8.5 closes the cycle and asks instead, which needs no replayable checkpoint.
- §7.2 already makes each step durable in Leafi's own transaction.
- Optional: python-statemachine (MIT, no core deps) for the `ActivityStatus` lifecycle, so "a kind ends only in its listed statuses" is structural rather than tested.

Fallback, if the owner wants a framework: Burr (zero core deps, the app's own connection, telemetry removed), keeping Leafi's `checkpoint()` inside long actions. Trade-off: Leafi writes and owns the loop, `negotiate` and `checkpoint` (ADR-0017 §2), and gives up a graph visualiser and time-travel replay, which §9's decision replay partly covers.

Prototype must test: the flow in §7, plus these checks:

- Lines of orchestration code.
- p50/p95 of checkpoint + persist + dispatch over 200 mocked decisions.
- `SQLITE_BUSY` count while the supervisor holds a write lock.
- Windows install of each variant's wheels.
- Zero sockets under `tests/test_privacy.py`'s no-network run with the framework imported.

## 5. LLM calls

Need:

- Typed structured output.
- Fallback across tiers: Claude, then magpie, then Ollama.
- Routing by task type and difficulty.
- A few seconds per decision.
- Streaming for TTS is a plus.

Hard constraints:

- A filter sees every request.
- No telemetry.
- Leafi owns retries.
- Cancellation propagates.

Pkgs = packages resolved for Py 3.12 / Windows with the current pins (L45). The base (`anthropic` 0.120.2 + `openai` < 3 + `httpx`) resolves to **19**.

| Candidate | License | Latest (date) | Fits the 0.120 / `httpx` pin? | Structured output | Validation retry | Fallback | Custom HTTP client | SDK retries off | Telemetry default | Pkgs | Partial use |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Raw SDKs + pydantic** (`anthropic` 0.120.2, `openai` 2.54.0, opt. `ollama` 0.6.3) | anthropic per README / PyPI (L15, L16); openai Apache-2.0; ollama MIT (L44) | 0.120.2 (2026-07-28); openai 2.54.0 (2026-08-11) is the last 2.x (L15, L17) | yes | Anthropic `messages.parse(output_format=Model)` sends a JSON schema (L16). OpenAI `parse()` (L18). Ollama `format=<schema>` or `/v1` `response_format` (L34) | Leafi | Leafi | `http_client=` (L16, L18) | `max_retries=0` (L16, L18) | none | 19 | — |
| **PydanticAI** (`pydantic-ai-slim`) | MIT (L1) | 2.59.0 (2026-10-21) (L1) | **only ≤ 2.31.1** (2026-08-18); 2.33+ needs `anthropic ≥ 1.0` (L1, L2, L3) | Tool, Native or Prompted output (L5). Ollama Native output is grammar-constrained on self-hosted, `UserError` on Ollama Cloud (L7) | output retries, default 1 (L5) | `FallbackModel` on `ModelAPIError`, before the first stream event; **not on validation failure** (L4) | `http_client=` per provider (L3) | at 2.31.1 pass your own SDK client with `max_retries=0`; latest has `ModelSettings['max_retries']` and `request_timeout` (L3, L4, L47) | nothing sent unless Logfire/OTel is configured; stderr banner (L9); `genai-prices` downloads only on `UpdatePrices` (L13) | 25 / 33 | `Agent(output_type=…)` + `FallbackModel` over Leafi-built SDK clients. The `direct` API drops validation and retries (L6), so the typed path needs `Agent` |
| **Instructor** | MIT (L19) | 1.17.0 (2026-09-09) | yes, but hard-requires `openai` even for Claude (L19) | modes incl. `ANTHROPIC_TOOLS`, `JSON_SCHEMA` (L24); Ollama mode chosen by model name (L22) | re-ask; can take tenacity (L20) | none | wraps your client (`from_anthropic`, `patch`) (L24) | separately; the two layers multiply (L20) | none documented (L21) | 43 | `from_anthropic(own_client)`, still the whole 43-package tree |
| **LiteLLM** | MIT (L25) | 1.106.2 (2026-10-21) | resolves | `response_format=Model`; validation opt-in (L29) | none | Router fallbacks, cooldowns (L28) | module-global sessions only (L26) | `num_retries=0` (L28) | **fetches its model cost map from GitHub at import** unless `LITELLM_LOCAL_MODEL_COST_MAP=True` (L26); usage telemetry opt-out (L30) | **61** | no light slice |
| Outlines | Apache-2.0 (L32) | 1.3.3 (2026-08-06) | n/a | with Ollama: JSON schema only, through Ollama itself (L33) | none | none | `ollama.AsyncClient` | n/a | none | 25 | adds nothing over `ollama`'s `format=` |
| Mirascope v2 | MIT (L35) | 2.8.1 (2026-10-20) | yes | `format=` (L36) | *not verified* | *not verified* | `register_provider(base_url=)` (L36) | *not verified* | *not verified* | 20 | — |
| any-llm (Mozilla) | Apache-2.0 (L37) | 1.39.0 (2026-10-21) | **no** (`anthropic ≥ 0.124`) (L37) | *not verified* | — | — | — | — | — | 26 | — |
| BAML | not stated | 0.226.2 (2026-09-01) (L39) | own DSL and runtime | own parser | — | fallback client + retry policy (L39) | no Python httpx injection documented | — | — | n/a | — |
| aisuite / magentic / ell / DSPy / LangChain | various | aisuite 0.2.0; magentic 0.41.1 (2026-03-11); ell 0.0.17 (2025-02, stale); DSPy 3.4.1 depends on litellm; langchain-core pulls langsmith (L38, L40–L43) | — | — | — | — | — | — | — | — | — |

Constraint fit:

- **One Leafi-built HTTP client can carry all traffic** for: raw SDKs, PydanticAI ≤ 2.31.1, and Instructor over a Leafi-built client (L3, L16, L18, L24). PydanticAI also has `ProcessHistory`, a message-level hook before each request (L10). LiteLLM exposes only module-global sessions (L26).
- **Telemetry.** LiteLLM's import-time GitHub fetch conflicts with "every outbound call is in the egress table" (ADR-0011).
- **Deadline-triggered fallback.** At 2.31.1 PydanticAI has only a per-request `timeout`; a `request_timeout` that triggers fallback exists only in newer versions (L3, L4, L47).
- **Ollama.** Recommends temperature 0 and repeating the schema in the prompt (L34). Whether magpie forwards `response_format` intact is unknown.

Pitfalls:

- **Upgrade cost.** Upgrading PydanticAI past 2.31.1 forces the `anthropic` 1.x + `httpx2` migration (L1, L4).
- **`FallbackModel` limits.** It does not fall back on bad output (#2837 closed "not planned", L12) or after the first stream event (L4).
- **`OpenAIProvider` guesses a profile from the model name**, whatever the `base_url`. Structured output to magpie may be ignored until the profile is configured (L8).
- **LiteLLM supply-chain compromise.** Versions 1.82.7 and 1.82.8 (2026-03-24) were compromised on PyPI by a credential stealer (L27, T4 context L31).
- **Instructor hooks only observe**, so they cannot be the privacy filter (L21).
- **No `fallbacks` in `anthropic` 0.120.2** (TD-1, L46). Fallback stays Leafi-owned in every option.

**Recommendation.** A thin Leafi-owned client over the raw SDKs:

- `anthropic==0.120.2` `messages.parse(output_format=…)` for Claude.
- `openai<3` `AsyncOpenAI(base_url="http://127.0.0.1:3425/v1")` for magpie.
- Ollama `format=`.
- Pydantic validation and one re-ask.
- Leafi's own ordered fallback list, per-attempt deadline (§2) and routing table.
- All clients built by the egress module (§6) with `max_retries=0`.

Cost: about 200–300 lines of re-ask, fallback and streaming glue.

Runner-up: `pydantic-ai-slim[anthropic,openai]==2.31.1` with `Agent(output_type=…)` + `FallbackModel` over Leafi-built SDK clients. It brings typed output, output retries and `ProcessHistory`, but freezes Leafi on a release from 2026-08-18 while upstream ships about 56 releases a quarter. Re-evaluate it on latest when TD-1 lands, and choose it if the Brain grows agentic tool loops.

Reject:

- LiteLLM and DSPy: weight, import-time fetch, and the March 2026 compromise.
- any-llm: conflicts with the pin.
- ell and magentic: stale.
- Outlines: nothing over Ollama.
- Instructor: 43 packages to buy a re-ask.

Prototype must test:

1. **Privacy coverage.** A canary transport sees 100 % of requests on all three backends, including fallback attempts and streams, with no import-time network.
2. **Overhead.** p50/p95 of PydanticAI `Agent.run` vs raw `messages.parse` on the same model (n ≥ 50), plus cold import time on Windows.
3. **First-try validity** of the "choose activity" schema on the candidate Ollama model via `format=`, `/v1` and magpie (n ≥ 100, temperature 0, schema in and out of the prompt).
4. **Fallback** starts within budget when the server stalls before the first byte, stalls mid-stream, or returns 500, with no SDK retry. Outer cancellation closes the connection.
5. **Speech timing.** Time to first token for the spoken line, and whether one call can yield both the decision and a streamed line.
6. **Pins survive.** Installing the slice leaves `anthropic==0.120.2` and `httpx==0.28.1` and the suite green.

## 6. Egress mediation

ADR-0018 §2: egress is "mediated per request, backstopped at the socket" (E2).

Installed today: `anthropic` 0.120.2, `httpx` 0.28.1, `huggingface_hub` 1.16.1, `hf-xet` 1.7.0, `edge-tts` 7.2.8 (aiohttp), `ultralytics` 8.4.115, `transformers` 5.17.0. Not installed: pydantic-ai, logfire, litellm, langsmith, posthog (M1-E).

| Option | License | Latest (date) | Maintenance | Sees | Modify / refuse | Misses | Partial use |
|---|---|---|---|---|---|---|---|
| **A. httpx custom transport** (subclass `AsyncBaseTransport` wrapping `AsyncHTTPTransport`) | BSD-3 (E4) | httpx 0.28.1 (2024-12-06); httpx2 2.16.0 (2026-10-21) (E4, E14) | httpx last commit 2026-02-23; httpx2's README says httpx "is seeing limited activity" (E5, E15) | full request; `await request.aread()` buffers even a streaming body and replaces the stream (E8). Measured: canary in an async-generator body caught; about 3 µs added per request (72 vs 69 µs, 2,000 × 2 KB) (M1-E) | raise, or return a synthetic `Response` (E6, M1-E) | clients the mediator did not build; aiohttp; the other httpx family; native sockets; subprocesses | one ~50-line class, one subclass per httpx family |
| B. httpx `event_hooks["request"]` | same | same | same | request; hooks may modify it (E7) | refusing by raising works but is undocumented (M1-E) | per-client; a second client has none | audit tap on clients Leafi does not build |
| **C. SDK client injection** | anthropic, openai Apache-2.0; ollama MIT (E9, E16, E17) | anthropic 2.1.0; openai 3.36.1; ollama 0.6.3 (E9, E16, E17) | active | via A | via A | SDKs built without it; `DefaultAioHttpClient` bypasses httpx (E13) | anthropic/openai `http_client=`; ollama `transport=` (E17); huggingface_hub `set_client_factory`/`set_async_client_factory` (E41); edge-tts `connector=`/`proxy=` (E46) |
| D. mitmproxy | MIT (E27) | 12.3.0 (2026-10-22) | very active (E30) | full body only with TLS interception and a trusted CA (E28, E29) | yes | pinned clients; anything not using the proxy | event model as a design reference only |
| E. proxy.py allow-list | BSD (E31) | 2.4.10 (2025-02-18) | last commit 2025-03-23 (E32) | over TLS without MITM: **host and port only**, a CONNECT tunnel is a blind relay (E34) | `FilterByUpstreamHostPlugin` (E31) | bodies | only if a non-Python process ever needs an allow-listed path |
| F. tinyproxy | — | 1.11.3 (2026-03-07) | active | host only | allow-list | **no Windows build** (E33) | — |
| G. Windows Firewall per program | OS | — | — | process path, remote address and port; no hostnames, no bodies (E35) | block beats allow, no ordering, full paths only (E36) | shared interpreter; CDN IP churn | one Block rule on a Leafi-only interpreter, later |
| H. WFP / AppContainer | OS | — | — | per app, user, connection (E37, E38) | yes | — | out of proportion |
| **I. Socket guard (Leafi `netguard`)** | own | — | — | address and host; covers proactor `sock_connect` and `create_connection` (E3) | raise | Rust/C extensions with own sockets; subprocesses | grow deny-all into grants matched by address |
| J. `sys.addaudithook` | stdlib | — | — | `socket.connect`, `getaddrinfo`, `subprocess.Popen` (E18) | a hook may raise (E19); cannot be removed (E20) | **the Windows proactor connect emits no `socket.connect` event** (`ConnectEx`, no `PySys_Audit` in `overlapped.c`); measured: not blocked (E21, E22, M1-E). Docs: not a sandbox (E19) | monitor-only tap for `subprocess.Popen` |
| K. pytest-socket | MIT (E23) | 0.8.1 (2026-08-19) | active | address | `GuardedSocket` (E24) | no asyncio handling (E24) | pattern only; netguard already covers asyncio |
| L. respx / pytest-httpx | BSD-3 / MIT (E25, E26) | 0.23.1 / 0.36.2 (pins httpx 0.28) | active | full request | mock, assert all requests expected (E26) | do not see `httpx2` SDK traffic without `alias_httpx()` (E13) | recorder belongs in the mediator instead |

Constraint fit:

- **Per-request policy.** Only A–C see the per-learner setting, the consent and the body. G–J see addresses.
- **Non-httpx clients need gates at the call site.** These are edge-tts (aiohttp websockets), gTTS and urllib in `doctor` (E45, E46, M1-E). Whether aiohttp middlewares cover `ws_connect` is *not verified* (E47).
- **Admin.** G and H need it (E37) and are one-time setup, not runtime policy.

Pitfalls:

- **Two httpx families** (finding 0.1).
- **SDK retries re-send a refused request.** A refusal raised in the transport becomes `APIConnectionError` and is retried twice; 403 is not retried. So refuse with a synthetic 403 carrying a reason body (E13, M1-E).
- **The venv `python.exe` on Windows is a launcher.** The real process is the base Scoop interpreter, so a firewall rule on `.venv\Scripts\python.exe` does not apply (E39, M1-E).
- **Loopback must stay allowed in any connect block.** The proactor's self-pipe uses a loopback `socketpair` (M1-E).
- **Telemetry in the installed stack.** Hugging Face libraries send telemetry unless `HF_HUB_DISABLE_TELEMETRY=1`/`DO_NOT_TRACK=1` or offline mode; these are read at import (E40, E41). Ultralytics `sync` defaults to True (E44).
- **`hf-xet` is a Rust extension that Hub transfers go through** (E40, E43). Python socket patches cannot see it (*inferred*); set `HF_HUB_DISABLE_XET=1`.
- **edge-tts creates its session with `trust_env=True`** (E46), so an environment proxy reroutes it.

**Recommendation.** Three layers, two of them now.

1. **Mediator.** `leafi/core/egress` builds every client: a `MediatedTransport` for each httpx family, passed through the SDK seams listed in row C. The transport does all of the following:
   - Reads the body.
   - Matches the host against the egress table (E1).
   - Refuses media unless a consent row is consumed atomically.
   - Pseudonymises per `cloud.text`.
   - Logs to `egress_log` (E2).
   - Refuses with a 403 and a reason body.

   Non-httpx libraries get explicit gate calls before use.
2. **Backstop.** `netguard` grows from deny-all into grants: `getaddrinfo` resolves only granted names and records their IPs; `connect` allows loopback, table LAN devices, and IPs of currently granted names. Add a monitor-only audit hook for `subprocess.Popen`. Set `HF_HUB_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK` and `HF_HUB_DISABLE_XET` before imports, and turn Ultralytics `sync` off.
3. **Later, only if a native-socket leak is observed:** an OS firewall rule on a Leafi-only interpreter.

Rejected:

- mitmproxy: weight, and a CA key in a child's home (E27, E29).
- proxy.py and tinyproxy: blind to bodies over TLS; no Windows build for tinyproxy (E33, E34).
- WFP and AppContainer: cost.
- Audit hooks as the gate: blind on the proactor.

Trade-off: two transport subclasses until TD-1. Alternatively, `httpx2.alias_httpx()` at the very start of `leafi.cli` collapses them, at the risk that some dependency relies on `httpx`-only behaviour.

Prototype must test:

1. A canary (learner name, audio bytes) in a JSON body, a streamed body and a multipart upload never reaches the inner transport.
2. A refusal is logged once, not three times.
3. `AsyncAnthropic()` without the client, `DefaultAioHttpClient()`, a bare `httpx.AsyncClient()` and a bare `aiohttp.ClientSession()` are each stopped by netguard under the proactor. Test against 127.0.0.2 as a non-granted stand-in, so nothing leaves the machine.
4. Two concurrent media requests with one consent: exactly one passes.
5. Both httpx families are covered, or `alias_httpx()` is proven to run first.
6. A DNS lookup of a non-granted name raises.
7. A subprocess spawn is logged.
8. Per-request p50/p99 overhead on a 4–20 KB Brain payload.
9. The full app with transformers, ultralytics and huggingface_hub imported shows zero denied connects in a text session.

## 7. Recommended combinations to prototype

The egress layer (§6) and cancel scopes (§2) are the same in both; they are not a library choice but the boundary every other choice must sit inside. The combinations differ where a library could replace hand-written code.

| | **Combination 1: "thin, own the loop"** (recommended) | **Combination 2: "library-backed"** |
|---|---|---|
| Migrations | own `user_version` runner + generic `rebuild()` helper | own runner + Alembic `Operations.batch_alter_table` (migrate command only) |
| Deadlines | anyio `CancelScope` + `TaskGroup` on asyncio | same |
| Retries | ~30-line loop with tenacity waits, absolute deadline, SDK `max_retries=0` | stamina `AsyncRetryingCaller` per call, `timeout=deadline-now` |
| Orchestration | hand-written loop (ADR-0017 §2) + optional python-statemachine for `ActivityStatus` | Burr `Application` + `AsyncSQLitePersister` on Leafi's connection, `checkpoint()` inside long actions |
| LLM calls | raw SDKs + pydantic + own fallback/routing | `pydantic-ai-slim==2.31.1` `Agent(output_type)` + `FallbackModel` over Leafi-built SDK clients |
| Egress | mediator transport + netguard grants | same |
| New packages (*inferred* from the rows above) | tenacity (0 deps), optionally python-statemachine (0 deps) | tenacity, stamina, apache-burr[+aiosqlite], pydantic-ai-slim slice (+6 to +14), SQLAlchemy, Mako |

Both run the same scripted flow with the mock Brain, `--mock` audio and recorded `--page-text` pages; nothing speaks on the camera:

1. **Read a page.** `read_listen` on page A produces three practice candidates.
2. **Practise wrong words.** The Brain chooses `practise_errors`.
3. **Page turn mid-activity.** During the second candidate, a page-turn event arrives. Expect status `page_turned`; the untouched candidate stays owned by the cycle (ADR-0017 §8.2).
4. **Stop and deadline inside a `listen`.** Inject a parent stop, a session-deadline expiry and a lease loss inside an awaited `listen`. Expect each to end the activity within one await, with no speech after `lease_lost`.
5. **Crash and resume.** Kill the process (`TerminateProcess`) during the Brain call, between the effects commit and the activity-row commit, and during practice. After restart, expect:
   - no duplicated miscue or ledger rows;
   - the activity `interrupted`, the cycle closed;
   - one "continue from page N?" prompt.
6. **Pause to ask.** At autonomy 2, silence and then "skip" consume exactly one skip.

What to measure, per combination:

| Measure | How |
|---|---|
| Code size | Lines of harness code Leafi owns (loop, retry, fallback, migration helper), excluding domain logic; plus resolved package count and Windows install size |
| Latency added per decision | p50/p95 over 200 mocked decisions of everything except the model call (checkpoint, persist, dispatch, validation, egress filter); plus per-call overhead of the LLM layer vs a raw `messages.parse` (n ≥ 50) |
| Cancellation | Time from event (page turn, stop, deadline) to the activity row being final; whether shielded cleanup ran within its budget; open connections afterwards |
| Resume | Duplicated side effects after each kill point (the framework variant also counts re-run nodes); the state the learner is offered on restart |
| Privacy | `tests/test_privacy.py` canary and no-network run green with every library imported; zero import-time sockets |
| Migration | A CHECK/UNIQUE/NOT NULL change with the supervisor holding the file: data intact, clean refusal under lock |

Exit criterion *(proposed)*: Combination 2 replaces Combination 1 in a mechanism only where it removes more hand-written code than it adds glue, without failing any row above.

## 8. Open questions and gaps

- **Unverified installs.** That the `sqlite-vec` (LangGraph saver) and DBOS wheels install and run on Windows.
- **Unverified behaviour:**
  - whether pydantic-graph's `logfire-api` sends anything when Logfire is unconfigured;
  - whether aiohttp middlewares cover `ws_connect`;
  - Mirascope, BAML and any-llm details;
  - whether magpie passes `response_format` through.
- **Inferred, not tested.** Python socket patches cannot see `hf-xet`'s Rust sockets.
- **Upgrade baseline.** TD-1 (move to `anthropic` ≥ 1.x + `httpx2`) changes the baseline of §3, §5 and §6. Prototypes should be written so the transport and retry layer can be swapped to `httpx2` without touching domain code.
- **Measurement gaps.** GitHub API rate limits meant LLM-library maintenance was measured by PyPI release cadence (L45), not by commits.
- **Content found while fetching.** Pages fetched from pydantic.dev contained text addressed to agents; it was ignored as data.

## 9. Sources

All rows checked 2026-10-22. "Undated" = an undated living page or source file on a default branch.

### 9.1 Migrations (M)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| M1 | T1 | PyPI alembic — https://pypi.org/pypi/alembic/json | 1.20.1, 2026-10-22 | 2026-10-22 | license, version, deps, cadence |
| M2 | T1 | GitHub API alembic commits — https://api.github.com/repos/sqlalchemy/alembic/commits?per_page=1 | 2026-10-22 | 2026-10-22 | maintenance |
| M3 | T1 | Alembic batch migrations — https://alembic.sqlalchemy.org/en/latest/batch.html | undated (1.20.1 docs) | 2026-10-22 | move-and-copy, CHECK handling, FK duty |
| M4 | T3 | alembic/operations/batch.py — https://github.com/sqlalchemy/alembic/blob/main/alembic/operations/batch.py | undated | 2026-10-22 | index recreation; no trigger handling |
| M5 | T3 | alembic/ddl/sqlite.py — https://github.com/sqlalchemy/alembic/blob/main/alembic/ddl/sqlite.py | undated | 2026-10-22 | `transactional_ddl = False` |
| M6 | T1 | Alembic operation reference — https://alembic.sqlalchemy.org/en/latest/ops.html | undated | 2026-10-22 | standalone `Operations` |
| M7 | T1 | Alembic cookbook — https://alembic.sqlalchemy.org/en/latest/cookbook.html | undated | 2026-10-22 | `--check-heads` |
| M8 | T1 | SQLAlchemy 2.1 SQLite dialect — https://docs.sqlalchemy.org/en/21/dialects/sqlite.html | undated | 2026-10-22 | pysqlite transactions, `autocommit=False` |
| M9 | T1 | PyPI SQLAlchemy — https://pypi.org/pypi/sqlalchemy/json | 2.1.6, 2026-10-21 | 2026-10-22 | deps, py ≥ 3.11 |
| M10 | T1 | PyPI sqlite-utils — https://pypi.org/pypi/sqlite-utils/json | 4.2.1, 2026-08-13 | 2026-10-22 | license, deps |
| M11 | T1 | GitHub API sqlite-utils commits — https://api.github.com/repos/simonw/sqlite-utils/commits?per_page=1 | 2026-10-11 | 2026-10-22 | maintenance |
| M12 | T1 | sqlite-utils Python API — https://sqlite-utils.datasette.io/en/stable/python-api.html | undated | 2026-10-22 | `transform` parameters, FK behaviour |
| M13 | T3 | sqlite_utils/db.py — https://github.com/simonw/sqlite-utils/blob/main/sqlite_utils/db.py | undated | 2026-10-22 | CHECK/UNIQUE kept, index rules, legacy_alter_table, `atomic()` |
| M14 | T1 | sqlite-utils migrations — https://sqlite-utils.datasette.io/en/stable/migrations.html | undated | 2026-10-22 | `pending()` |
| M15 | T1 | simonw/sqlite-migrate — https://github.com/simonw/sqlite-migrate | archived 2026-07-07 | 2026-10-22 | archived |
| M16 | T1 | PyPI yoyo-migrations — https://pypi.org/pypi/yoyo-migrations/json | 9.0.0, 2024-08-10 | 2026-10-22 | license, release gap |
| M17 | T1 | yoyo docs — https://ollycope.com/software/yoyo/latest/ | undated | 2026-10-22 | lock table, no ALTER helpers |
| M18 | T1 | Atlas Community Edition — https://atlasgo.io/community-edition | undated | 2026-10-22 | licenses, Pro-only features |
| M19 | T1 | Atlas applying migrations — https://atlasgo.io/versioned/apply | undated | 2026-10-22 | tx-mode, status, lock |
| M20 | T3 | atlas sql/sqlite/migrate.go — https://github.com/ariga/atlas/blob/master/sql/sqlite/migrate.go | undated | 2026-10-22 | rebuild plan, FK pragma comment |
| M21 | T1 | Atlas dev database — https://atlasgo.io/concepts/dev-database | undated | 2026-10-22 | dev DB needed |
| M22 | T1 | GitHub API atlas releases — https://api.github.com/repos/ariga/atlas/releases | v1.3.0, 2026-08-02 | 2026-10-22 | release, maintenance |
| M23 | T1 | amacneil/dbmate — https://github.com/amacneil/dbmate | v2.37.0, 2026-10-18 | 2026-10-22 | no rebuild; lock PG only |
| M24 | T3 | peewee playhouse/migrate.py — https://github.com/coleifer/peewee/blob/master/playhouse/migrate.py | peewee 4.5.3, 2026-10-07 | 2026-10-22 | `NotImplementedError` on SQLite constraints |
| M25 | T1 | PyPI peewee-migrate — https://pypi.org/pypi/peewee-migrate/json | 2.3.0, 2026-08-24 | 2026-10-22 | needs ORM |
| M26 | T1 | clutchski/caribou — https://github.com/clutchski/caribou | 0.6.0, 2026-02-06 | 2026-10-22 | zero deps |
| M27 | T1 | jasondcamp/pyway — https://github.com/jasondcamp/pyway | 0.3.33, 2026-07-23 | 2026-10-22 | GPL, heavy deps |
| M28 | T1 | SQLite ALTER TABLE — https://www.sqlite.org/lang_altertable.html | updated 2026-10-05 | 2026-10-22 | 12-step procedure, ordering |
| M29 | T1 | SQLite 3.53.0 release log — https://www.sqlite.org/releaselog/3_53_0.html | 2026-04-09 | 2026-10-22 | native NOT NULL/CHECK ALTER |
| M30 | T1 | SQLite transactions — https://www.sqlite.org/lang_transaction.html | updated 2026-02-18 | 2026-10-22 | IMMEDIATE, COMMIT BUSY |
| M31 | T1 | Python 3.12 sqlite3 — https://docs.python.org/3.12/library/sqlite3.html | undated | 2026-10-22 | `executescript` commit, autocommit |
| M32 | T3 | Local measurement: `.venv\Scripts\python -c "import sqlite3; print(sqlite3.sqlite_version)"` | 2026-10-22 | 2026-10-22 | Python 3.12.10, SQLite 3.49.1 |
| M33 | T1 | Leafi `leafi/core/storage.py` | HEAD 72deb56 | 2026-10-22 | CASCADE FKs, pragmas, no WAL, no triggers |
| M34 | T1 | GitHub API: caribou, sqitch, goose, sqldef | per repo | 2026-10-22 | maintenance only |

### 9.2 Deadlines (D) and retries (R)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| D1 | T1 | PyPI anyio — https://pypi.org/pypi/anyio/json | 4.15.1, 2026-09-05; 4.14.2, 2026-07-12 | 2026-10-22 | license, deps, cadence |
| D2 | T1 | anyio cancellation — https://anyio.readthedocs.io/en/stable/cancellation.html | undated (4.15) | 2026-10-22 | level vs edge, shielded cleanup, LIFO, native tasks |
| D3 | T1 | anyio API — https://anyio.readthedocs.io/en/stable/api.html | undated | 2026-10-22 | `CancelScope(deadline)`, `move_on_at`, `abandon_on_cancel`, timer start |
| D4 | T1 | anyio threads — https://anyio.readthedocs.io/en/stable/threads.html | undated | 2026-10-22 | threads not cancellable |
| D5 | T1 | anyio version history — https://anyio.readthedocs.io/en/stable/versionhistory.html | to 4.15.1 | 2026-10-22 | fixes and feature versions |
| D6 | T1 | anyio "Why AnyIO" — https://anyio.readthedocs.io/en/stable/why.html | undated | 2026-10-22 | shields vs `Task.cancel()` |
| D7 | T1 | Python asyncio tasks — https://docs.python.org/3/library/asyncio-task.html | undated | 2026-10-22 | `timeout_at`, `uncancel`, `shield`, 3.13 TaskGroup change |
| D8 | T1 | CPython #102780 — https://github.com/python/cpython/issues/102780 | 2023-03-17 to 2023-03-22 | 2026-10-22 | swallowed cancellation |
| D9 | T1 | CPython #116720 — https://github.com/python/cpython/issues/116720 | 2024-03-13 to 2024-04-09 | 2026-10-22 | TaskGroup lost cancellation on 3.12 |
| D10 | T1 | Python event loop — https://docs.python.org/3/library/asyncio-eventloop.html | undated | 2026-10-22 | `shutdown_default_executor(timeout)` |
| D11 | T1 | Python concurrent.futures — https://docs.python.org/3/library/concurrent.futures.html | undated | 2026-10-22 | running call not cancellable |
| D12 | T1 | asyncio platform support — https://docs.python.org/3/library/asyncio-platforms.html | undated | 2026-10-22 | Proactor, clock resolution |
| D13 | T4 | discuss.python.org: anyio/Trio patterns into asyncio — https://discuss.python.org/t/adopt-proven-anyio-trio-patterns-natively-into-asyncio-multi-release-roadmap/106067 | 2026-02-08 to 2026-03-01 | 2026-10-22 | reported: no cancel or shield scope in asyncio |
| D14 | T1 | PyPI trio — https://pypi.org/pypi/trio/json | 0.34.0, 2026-08-11 | 2026-10-22 | license, version |
| D15 | T1 | trio reference — https://trio.readthedocs.io/en/stable/reference-core.html | undated | 2026-10-22 | caller-owned deadlines, shielded cleanup |
| D16 | T1 | PyPI quattro — https://pypi.org/pypi/quattro/json | 26.1.0, 2026-03-31 | 2026-10-22 | license, deps, API |
| D17 | T1 | GitHub API quattro — https://api.github.com/repos/Tinche/quattro/commits?per_page=2 | 2026-09-30 | 2026-10-22 | maintenance |
| D18 | T1 | PyPI aiotools — https://pypi.org/pypi/aiotools/2.2.4/json | 2.2.4, 2026-07-21 | 2026-10-22 | license, features |
| D19 | T1 | PyPI async-timeout — https://pypi.org/pypi/async-timeout/json | 5.0.1, 2024-11-06 | 2026-10-22 | deprecated |
| D20 | T1 | httpcore PR #1099 — https://github.com/encode/httpcore/pull/1099 | opened 2026-07-25, open | 2026-10-22 | pool leak on cancel |
| D21 | T1 | httpcore releases — https://api.github.com/repos/encode/httpcore/releases?per_page=1 | 1.0.9, 2025-04-24 | 2026-10-22 | latest release |
| D22 | T1 | httpx releases — https://api.github.com/repos/encode/httpx/releases?per_page=2 | 0.28.1, 2024-12-06 | 2026-10-22 | latest release |
| R1 | T1 | PyPI tenacity — https://pypi.org/pypi/tenacity/json | 9.2.1, 2026-10-07 | 2026-10-22 | license, no deps |
| R2 | T1 | GitHub API tenacity — https://api.github.com/repos/jd/tenacity/commits?per_page=3 | 2026-10-12 | 2026-10-22 | maintenance |
| R3 | T1 | tenacity docs — https://tenacity.readthedocs.io/en/latest/ | undated | 2026-10-22 | async, statistics |
| R4 | T1 | tenacity API — https://tenacity.readthedocs.io/en/latest/api.html | undated | 2026-10-22 | wait strategies, `retry_if_exception` |
| R5 | T3 | tenacity/stop.py — https://raw.githubusercontent.com/jd/tenacity/main/tenacity/stop.py | undated | 2026-10-22 | relative stop semantics |
| R6 | T1 | PyPI stamina — https://pypi.org/pypi/stamina/json | 26.1.0, 2026-04-13 | 2026-10-22 | license, deps |
| R7 | T1 | GitHub API stamina — https://api.github.com/repos/hynek/stamina/commits?per_page=3 | 2026-10-19 | 2026-10-22 | maintenance |
| R8 | T1 | stamina API — https://stamina.hynek.me/en/stable/api.html | undated | 2026-10-22 | defaults, `on` hook, `set_testing`, hooks |
| R9 | T3 | stamina/_core.py — https://raw.githubusercontent.com/hynek/stamina/main/src/stamina/_core.py | undated | 2026-10-22 | relative timeout, unclamped custom backoff |
| R10 | T1 | PyPI backoff — https://pypi.org/pypi/backoff/json | 2.2.1, 2022-10-05 | 2026-10-22 | last release |
| R11 | T1 | GitHub API backoff — https://api.github.com/repos/litl/backoff/commits?per_page=3 | 2023-01-20 | 2026-10-22 | inactive |
| R12 | T1 | backoff README — https://raw.githubusercontent.com/litl/backoff/master/README.rst | undated | 2026-10-22 | async, max_time |
| R13 | T1 | httpx transports — https://www.python-httpx.org/advanced/transports/ | undated | 2026-10-22 | `retries=` connect errors only |
| R14 | T1 | PyPI/README httpx-retries — https://pypi.org/pypi/httpx-retries/json | 0.6.0, 2026-07-06 | 2026-10-22 | deps, body-read limit |
| R15 | T3 | httpx_retries/retry.py — https://raw.githubusercontent.com/will-ockmore/httpx-retries/main/httpx_retries/retry.py | undated | 2026-10-22 | no POST, Retry-After cap |
| R16 | T1 | PyPI aiohttp-retry — https://pypi.org/pypi/aiohttp-retry/json | 2.9.1, 2024-11-06 | 2026-10-22 | license, deps |
| R17 | T1 | GitHub API aiohttp_retry — https://api.github.com/repos/inyutin/aiohttp_retry/commits?per_page=2 | 2026-04-08 | 2026-10-22 | maintenance |
| R18 | T1 | PyPI anthropic — https://pypi.org/pypi/anthropic/json | 2.1.0, 2026-10-21; 0.120.2, 2026-07-28 | 2026-10-22 | versions |
| R19 | T1 | Claude Python SDK docs — https://platform.claude.com/docs/en/api/sdks/python | undated (SDK 2.x) | 2026-10-22 | default retries, `max_retries=0`, timeout, `httpx2` |
| R20 | T3 | anthropic v0.120.2 `_base_client.py` — https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/v0.120.2/src/anthropic/_base_client.py | tag v0.120.2 | 2026-10-22 | retry classification, Retry-After ≤ 60, `except Exception` |
| R21 | T3 | anthropic v0.120.2 `_constants.py` — https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/v0.120.2/src/anthropic/_constants.py | tag v0.120.2 | 2026-10-22 | 600 s timeout, 2 retries, 0.5–8 s |
| R22 | T1 | PyPI pydantic-ai-slim — https://pypi.org/pypi/pydantic-ai-slim/2.59.0/json | 2.59.0, 2026-10-21 | 2026-10-22 | `retries` extra |
| R23 | T1 | pydantic-ai retries — https://pydantic.dev/docs/ai/advanced-features/retries/ | undated | 2026-10-22 | retry stacking, `wait_retry_after` |

### 9.3 Orchestration (O)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| O1 | T1 | PyPI langgraph — https://pypi.org/pypi/langgraph/json | 1.2.16, 2026-10-16 | 2026-10-22 | version, deps |
| O2 | T1 | PyPI langgraph-checkpoint-sqlite — https://pypi.org/pypi/langgraph-checkpoint-sqlite/json | 3.1.2, 2026-10-12 | 2026-10-22 | aiosqlite, sqlite-vec |
| O3 | T1 | PyPI langchain-core — https://pypi.org/pypi/langchain-core/json | 1.6.13 (date not retrieved) | 2026-10-22 | langsmith, httpx, tenacity deps |
| O4 | T1 | LangGraph interrupts — https://docs.langchain.com/oss/python/langgraph/interrupts | undated | 2026-10-22 | node re-runs, index matching |
| O5 | T1 | LangGraph checkpointers / durable execution — https://docs.langchain.com/oss/python/langgraph/durable-execution | undated | 2026-10-22 | durability modes, step boundaries |
| O6 | T1 | AsyncSqliteSaver reference — https://reference.langchain.com/python/langgraph.checkpoint.sqlite/checkpoint/sqlite/aio/AsyncSqliteSaver | undated | 2026-10-22 | own connection, non-production, hang |
| O7 | T1 | GitHub API langgraph — https://api.github.com/repos/langchain-ai/langgraph/commits?per_page=1 | 2026-10-21 | 2026-10-22 | maintenance |
| O8 | T1 | LangSmith tracing — https://docs.langchain.com/langsmith/trace-with-langchain | undated | 2026-10-22 | opt-in tracing |
| T4-1 | T4 | LangChain forum: StateGraph after cancellation — https://forum.langchain.com/t/stategraph-does-not-continue-state-transitions-after-task-cancellation/2678 | 2026-01-07 | 2026-10-22 | reported: no cleanup node |
| O9 | T1 | PyPI pipecat-ai-flows — https://pypi.org/pypi/pipecat-ai-flows/json | 1.4.0, 2026-07-05 | 2026-10-22 | deprecated, frozen |
| O10 | T1 | Pipecat Flows migration — https://docs.pipecat.ai/pipecat/migration/flows | undated | 2026-10-22 | moved into pipecat-ai |
| O11 | T1 | Pipecat FlowManager — https://docs.pipecat.ai/api-reference/pipecat-flows/flow-manager | undated | 2026-10-22 | requires LLMService, state dict |
| O12 | T1 | Pipecat Flows guide — https://docs.pipecat.ai/guides/features/pipecat-flows | undated | 2026-10-22 | cascaded pipeline, node model |
| O13 | T1 | PyPI pipecat-ai — https://pypi.org/pypi/pipecat-ai/json | 1.13.0 (date not retrieved) | 2026-10-22 | weight |
| O14 | T1 | PyPI pydantic-graph — https://pypi.org/pypi/pydantic-graph/2.59.0/json | 2.59.0, 2026-10-21 | 2026-10-22 | deps |
| O15 | T1 | Pydantic graph builder — https://pydantic.dev/docs/ai/graph/builder/ | undated | 2026-10-22 | persistence removed in V2; `iter()` |
| O16 | T1 | GitHub API pydantic-ai — https://api.github.com/repos/pydantic/pydantic-ai/commits?per_page=1 | 2026-10-22 | 2026-10-22 | maintenance |
| O17 | T1 | PyPI apache-burr — https://pypi.org/pypi/apache-burr/json | 0.43.0, 2026-08-25 | 2026-10-22 | zero core deps |
| O18 | T1 | Burr persisters — https://burr.apache.org/reference/persister/ | undated | 2026-10-22 | own connection, table |
| O19 | T1 | Burr state persistence — https://burr.apache.org/concepts/state-persistence/ | undated | 2026-10-22 | write per action, resume |
| O20 | T1 | Burr state machine — https://burr.apache.org/concepts/state-machine/ | undated | 2026-10-22 | halt, inputs caveat |
| O21 | T1 | Burr tracking — https://burr.apache.org/concepts/tracking/ | undated | 2026-10-22 | opt-in tracker |
| O22 | T3 | burr/telemetry.py at v0.43.0 — https://raw.githubusercontent.com/apache/burr/v0.43.0-incubating/burr/telemetry.py | tag 0.43.0 | 2026-10-22 | telemetry removed |
| O23 | T1 | GitHub API burr — https://api.github.com/repos/apache/burr/commits?per_page=1 | 2026-10-19 | 2026-10-22 | maintenance |
| O24 | T1 | PyPI dbos — https://pypi.org/pypi/dbos/3.3.0/json | 3.3.0, 2026-10-15 | 2026-10-22 | deps incl. psycopg |
| O25 | T1 | DBOS configuration — https://docs.dbos.dev/python/reference/configuration | undated | 2026-10-22 | SQLite system DB, polling |
| O26 | T1 | DBOS workflows — https://docs.dbos.dev/python/tutorials/workflow-tutorial | undated | 2026-10-22 | determinism |
| O27 | T1 | DBOS workflow management — https://docs.dbos.dev/python/tutorials/workflow-management | undated | 2026-10-22 | cancel at next step |
| O28 | T1 | DBOS communication — https://docs.dbos.dev/python/tutorials/workflow-communication | undated | 2026-10-22 | `recv` timeouts |
| O29 | T3 | dbos/_dbos_config.py — https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_dbos_config.py | undated | 2026-10-22 | OTLP off |
| O30 | T1 | GitHub API dbos — https://api.github.com/repos/dbos-inc/dbos-transact-py/commits?per_page=1 | 2026-10-20 | 2026-10-22 | maintenance |
| O31 | T1 | PyPI temporalio — https://pypi.org/project/temporalio/1.34.0/ | 1.34.0, 2026-09-30 | 2026-10-22 | server required |
| O32 | T1 | PyPI python-statemachine — https://pypi.org/pypi/python-statemachine/json | 3.2.2, 2026-10-14 | 2026-10-22 | no deps, async |
| O33 | T1 | python-statemachine models — https://python-statemachine.readthedocs.io/en/latest/models.html | undated | 2026-10-22 | external model state |
| O34 | T1 | GitHub API python-statemachine — https://api.github.com/repos/fgmacedo/python-statemachine/commits?per_page=1 | 2026-10-16 | 2026-10-22 | maintenance |
| O35 | T1 | PyPI transitions — https://pypi.org/pypi/transitions/json | 0.9.3, 2025-07-02 | 2026-10-22 | license, AsyncMachine |
| O36 | T1 | GitHub API transitions — https://api.github.com/repos/pytransitions/transitions/commits?per_page=1 | 2025-09-09 | 2026-10-22 | slow maintenance |
| O37 | T1 | PyPI llama-index-workflows — https://pypi.org/pypi/llama-index-workflows/json | 2.26.1, 2026-10-21 | 2026-10-22 | deps, resume claim |
| T4-2 | T4 | CSDN tutorial on `Context.to_dict` — https://damodev.csdn.net/6aa3cb771a35784c8420f1ea.html | undated | 2026-10-22 | reported API |
| O38 | T1 | PyPI restate-sdk — https://pypi.org/pypi/restate-sdk/json | 1.1.0 (date not retrieved) | 2026-10-22 | server-tied |
| O39 | T1 | PyPI prefect — https://pypi.org/pypi/prefect/json | 3.9.0 (date not retrieved) | 2026-10-22 | 57 deps |
| O40 | T1 | PyPI hatchet-sdk — https://pypi.org/pypi/hatchet-sdk/json | 1.42.1 (date not retrieved) | 2026-10-22 | engine required |

### 9.4 LLM calls (L)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| L1 | T1 | PyPI pydantic-ai-slim — https://pypi.org/pypi/pydantic-ai-slim/json | 2.59.0, 2026-10-21 | 2026-10-22 | license, `httpx2`, `anthropic` floor by version |
| L2 | T1 | PyPI pydantic-ai-slim 2.31.1 — https://pypi.org/pypi/pydantic-ai-slim/2.31.1/json | 2026-08-18 | 2026-10-22 | last `httpx` core |
| L3 | T3 | pydantic-ai v2.31.1 source — https://github.com/pydantic/pydantic-ai/tree/v2.31.1/pydantic_ai_slim/pydantic_ai | tag v2.31.1 | 2026-10-22 | `http_client`, output_format, settings |
| L4 | T1 | Pydantic AI models overview — https://pydantic.dev/docs/ai/models/overview/ | undated | 2026-10-22 | `FallbackModel` triggers, `request_timeout` |
| L5 | T1 | Pydantic AI output — https://pydantic.dev/docs/ai/core-concepts/output/ | undated | 2026-10-22 | output modes, retries |
| L6 | T1 | Pydantic AI direct API — https://pydantic.dev/docs/ai/direct/ | undated | 2026-10-22 | no validation in direct |
| L7 | T1 | Pydantic AI Ollama — https://pydantic.dev/docs/ai/models/ollama/ | undated | 2026-10-22 | native output self-hosted |
| L8 | T1 | Pydantic AI compatible APIs — https://pydantic.dev/docs/ai/models/compatible-apis/ | undated | 2026-10-22 | profile guessed from model name |
| L9 | T1 | Pydantic AI Logfire — https://pydantic.dev/docs/ai/integrations/logfire/ | undated | 2026-10-22 | nothing sent unless configured |
| L10 | T1 | Pydantic AI message history — https://pydantic.dev/docs/ai/core-concepts/message-history/ | undated | 2026-10-22 | `ProcessHistory` |
| L11 | T1 | pydantic-ai #3104 — https://github.com/pydantic/pydantic-ai/issues/3104 | 2025-10-07 to 2025-11-05 | 2026-10-22 | fixed fallback/native output |
| L12 | T1 | pydantic-ai #2837 — https://github.com/pydantic/pydantic-ai/issues/2837 | closed 2026-10-13 | 2026-10-22 | no fallback on bad output |
| L13 | T1 | genai-prices README — https://github.com/pydantic/genai-prices/blob/main/packages/python/README.md | undated | 2026-10-22 | download only on `UpdatePrices` |
| L14 | T1 | pydantic/httpx2 — https://github.com/pydantic/httpx2 | first release 2026-05-11 | 2026-10-22 | continuation of httpx |
| L15 | T1 | PyPI anthropic — https://pypi.org/pypi/anthropic/json | 2.1.0, 2026-10-21; 1.0.0, 2026-08-20 | 2026-10-22 | 1.x on `httpx2` |
| L16 | T3 | anthropic-sdk-python v0.120.2 — https://github.com/anthropics/anthropic-sdk-python/tree/v0.120.2 | 2026-07-28 | 2026-10-22 | retries, timeout, `parse`, `http_client` |
| L17 | T1 | PyPI openai — https://pypi.org/pypi/openai/json | 3.0.0, 2026-08-12; 2.54.0, 2026-08-11 | 2026-10-22 | 3.x on `httpx2` |
| L18 | T3 | openai-python v2.54.0 — https://github.com/openai/openai-python/tree/v2.54.0 | 2026-08-11 | 2026-10-22 | retries, `parse()` |
| L19 | T1 | PyPI instructor — https://pypi.org/pypi/instructor/json | 1.17.0, 2026-09-09 | 2026-10-22 | deps |
| L20 | T1 | Instructor retrying — https://python.useinstructor.com/concepts/retrying/ | undated | 2026-10-22 | `max_retries`, layers |
| L21 | T1 | Instructor hooks — https://python.useinstructor.com/concepts/hooks/ | undated | 2026-10-22 | observe only |
| L22 | T1 | Instructor Ollama — https://python.useinstructor.com/integrations/ollama/ | undated | 2026-10-22 | mode by model |
| L23 | T1 | Instructor Anthropic — https://python.useinstructor.com/integrations/anthropic/ | undated | 2026-10-22 | modes, partial caveat |
| L24 | T3 | Instructor source — https://github.com/567-labs/instructor/tree/main/instructor | undated | 2026-10-22 | `from_anthropic`, modes |
| L25 | T1 | PyPI litellm — https://pypi.org/pypi/litellm/json | 1.106.2, 2026-10-21 | 2026-10-22 | deps |
| L26 | T3 | litellm `__init__.py` — https://github.com/BerriAI/litellm/blob/main/litellm/__init__.py | undated | 2026-10-22 | import-time cost-map fetch, sessions |
| L27 | T1 | LiteLLM security update — https://docs.litellm.ai/blog/security-update-march-2026 | 2026-03-24 | 2026-10-22 | 1.82.7/1.82.8 compromised |
| L28 | T1 | LiteLLM routing — https://docs.litellm.ai/docs/routing | undated | 2026-10-22 | fallbacks, `num_retries` |
| L29 | T1 | LiteLLM JSON mode — https://docs.litellm.ai/docs/completion/json_mode | undated | 2026-10-22 | `response_format` |
| L30 | T1 | LiteLLM telemetry (search snippet; page fetched empty) — https://docs.litellm.ai/docs/observability/telemetry | undated | 2026-10-22 | opt-out flag |
| L31 | T4 | Datadog Security Labs on LiteLLM — https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-teampcp-supply-chain-campaign/ | 2026-03 | 2026-10-22 | reported context |
| L32 | T1 | PyPI outlines — https://pypi.org/pypi/outlines/json | 1.3.3, 2026-08-06 | 2026-10-22 | license, deps |
| L33 | T1 | Outlines Ollama — https://dottxt-ai.github.io/outlines/latest/features/models/ollama/ | undated | 2026-10-22 | JSON schema only |
| L34 | T1 | Ollama structured outputs — https://docs.ollama.com/capabilities/structured-outputs | undated | 2026-10-22 | `format=`, `/v1`, temperature 0 |
| L35 | T1 | PyPI mirascope — https://pypi.org/pypi/mirascope/json | 2.8.1, 2026-10-20 | 2026-10-22 | deps |
| L36 | T1 | Mirascope providers — https://mirascope.com/docs/learn/llm/providers | undated | 2026-10-22 | `register_provider` |
| L37 | T1 | PyPI any-llm-sdk — https://pypi.org/pypi/any-llm-sdk/json | 1.39.0, 2026-10-21 | 2026-10-22 | pin conflict |
| L38 | T1 | PyPI aisuite — https://pypi.org/pypi/aisuite/json | 0.2.0, 2026-09-18 | 2026-10-22 | version |
| L39 | T1 | BAML fallback — https://docs.boundaryml.com/ref/llm-client-strategies/fallback | baml-py 0.226.2, 2026-09-01 | 2026-10-22 | fallback, retry policy |
| L40 | T1 | PyPI dspy — https://pypi.org/pypi/dspy/json | 3.4.1, 2026-10-12 | 2026-10-22 | depends on litellm |
| L41 | T1 | PyPI magentic — https://pypi.org/pypi/magentic/json | 0.41.1, 2026-03-11 | 2026-10-22 | stale |
| L42 | T1 | PyPI ell-ai — https://pypi.org/pypi/ell-ai/json | 0.0.17, 2025-02-25 | 2026-10-22 | stale |
| L43 | T1 | PyPI langchain-core — https://pypi.org/pypi/langchain-core/json | 2026-10-21 | 2026-10-22 | langsmith dep |
| L44 | T1 | PyPI ollama — https://pypi.org/pypi/ollama/json | 0.6.3, 2026-09-29 | 2026-10-22 | httpx, pydantic |
| L45 | T3 | Local measurement: `uv pip compile` for Py 3.12 / Windows with pins; PyPI release counts since 2026-07-24 | 2026-10-22 | 2026-10-22 | package counts, resolvability, cadence |
| L46 | T1 | Leafi `docs/plans/tech-debt.md` TD-1 | 2026-10-19 | 2026-10-22 | 0.120.2 pin, app-owned fallback |
| L47 | T3 | pydantic-ai main `settings.py` — https://github.com/pydantic/pydantic-ai/blob/main/pydantic_ai_slim/pydantic_ai/settings.py | undated | 2026-10-22 | `request_timeout`, `max_retries` |

### 9.5 Egress (E)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| E1 | T1 | Leafi `docs/architecture/quality-attributes/security.md` | HEAD 72deb56 | 2026-10-22 | egress table, privacy test |
| E2 | T1 | Leafi ADR-0018 §2–3 | HEAD 72deb56 | 2026-10-22 | mediated per request, socket backstop, consent |
| E3 | T1 | Leafi `leafi/core/netguard.py` | HEAD 72deb56 | 2026-10-22 | patched connect paths |
| E4 | T1 | PyPI httpx — https://pypi.org/pypi/httpx/json | 0.28.1, 2024-12-06 | 2026-10-22 | license, version |
| E5 | T1 | GitHub API httpx — https://api.github.com/repos/encode/httpx/commits?per_page=1 | 2026-02-23 | 2026-10-22 | maintenance |
| E6 | T1 | httpx transports — https://www.python-httpx.org/advanced/transports/ | undated | 2026-10-22 | custom transport pattern |
| E7 | T1 | httpx event hooks — https://www.python-httpx.org/advanced/event-hooks/ | undated | 2026-10-22 | hooks may modify |
| E8 | T3 | httpx `_models.py` — https://raw.githubusercontent.com/encode/httpx/master/httpx/_models.py | undated | 2026-10-22 | `aread()` replaces the stream |
| E9 | T1 | PyPI anthropic 2.1.0 — https://pypi.org/pypi/anthropic/2.1.0/json | 2026-10-21 | 2026-10-22 | license, `httpx2` |
| E10 | T1 | anthropic CHANGELOG — https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/CHANGELOG.md | 1.0.0 2026-08-20 | 2026-10-22 | move to `httpx2` |
| E11 | T1 | anthropic MIGRATION.md — https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/MIGRATION.md | undated | 2026-10-22 | `TypeError`, `alias_httpx` |
| E12 | T3 | anthropic `_base_client.py` (main) — https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/src/anthropic/_base_client.py | undated | 2026-10-22 | rejects httpx objects |
| E13 | T1 | Claude Python SDK docs — https://platform.claude.com/docs/en/api/sdks/python | undated | 2026-10-22 | `http_client`, retries, aiohttp backend, mocks |
| E14 | T1 | PyPI httpx2 — https://pypi.org/pypi/httpx2/json | 2.16.0, 2026-10-21 | 2026-10-22 | license, Python ≥ 3.11 |
| E15 | T1 | pydantic/httpx2 README — https://github.com/pydantic/httpx2 | pushed 2026-10-21 | 2026-10-22 | stewardship |
| E16 | T1 | PyPI openai 3.36.1 — https://pypi.org/pypi/openai/3.36.1/json | 2026-10-22 | 2026-10-22 | `httpx2` |
| E17 | T1 | PyPI ollama — https://pypi.org/pypi/ollama/json | 0.6.3, 2026-09-29 | 2026-10-22 | httpx, kwargs to client |
| E18 | T1 | Python audit events — https://docs.python.org/3/library/audit_events.html | undated | 2026-10-22 | events list |
| E19 | T1 | Python `sys.addaudithook` — https://docs.python.org/3/library/sys.html | undated | 2026-10-22 | may raise; not a sandbox |
| E20 | T1 | PEP 578 — https://peps.python.org/pep-0578/ | 2019 | 2026-10-22 | hooks not removable |
| E21 | T3 | CPython 3.12 `windows_events.py` — https://raw.githubusercontent.com/python/cpython/3.12/Lib/asyncio/windows_events.py | 3.12 branch | 2026-10-22 | `ConnectEx` path |
| E22 | T3 | CPython 3.12 `overlapped.c` — https://raw.githubusercontent.com/python/cpython/3.12/Modules/overlapped.c | 3.12 branch | 2026-10-22 | no audit call |
| E23 | T1 | PyPI pytest-socket — https://pypi.org/pypi/pytest-socket/json | 0.8.1, 2026-08-19 | 2026-10-22 | options, limits |
| E24 | T3 | pytest-socket source — https://raw.githubusercontent.com/miketheman/pytest-socket/main/src/pytest_socket/__init__.py | undated | 2026-10-22 | no asyncio handling |
| E25 | T1 | PyPI respx — https://pypi.org/pypi/respx/json | 0.23.1, 2026-04-08 | 2026-10-22 | license |
| E26 | T1 | PyPI pytest-httpx 0.36.2 — https://pypi.org/pypi/pytest-httpx/0.36.2/json | 2026-04-09 | 2026-10-22 | pins httpx 0.28 |
| E27 | T1 | PyPI mitmproxy — https://pypi.org/pypi/mitmproxy/json | 12.3.0, 2026-10-22 | 2026-10-22 | weight |
| E28 | T1 | mitmproxy events — https://docs.mitmproxy.org/stable/api/events.html | undated | 2026-10-22 | request event, CONNECT refusal |
| E29 | T1 | mitmproxy certificates — https://docs.mitmproxy.org/stable/concepts/certificates/ | undated | 2026-10-22 | CA must be trusted |
| E30 | T1 | GitHub API mitmproxy — https://api.github.com/repos/mitmproxy/mitmproxy/commits?per_page=1 | 2026-10-22 | 2026-10-22 | maintenance |
| E31 | T1 | PyPI proxy.py — https://pypi.org/pypi/proxy.py/json | 2.4.10, 2025-02-18 | 2026-10-22 | plugins, Windows notes |
| E32 | T1 | GitHub API proxy.py — https://api.github.com/repos/abhinavsingh/proxy.py/commits?per_page=1 | 2025-03-23 | 2026-10-22 | maintenance |
| E33 | T1 | GitHub API tinyproxy releases — https://api.github.com/repos/tinyproxy/tinyproxy/releases?per_page=1 | 1.11.3, 2026-03-07 | 2026-10-22 | no Windows binaries |
| E34 | T1 | RFC 9110 §3.7 — https://www.rfc-editor.org/rfc/rfc9110.html | 2022 | 2026-10-22 | tunnel is a blind relay |
| E35 | T1 | New-NetFirewallRule — https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule | updated 2025-05-14 | 2026-10-22 | per-program rules |
| E36 | T1 | Windows Firewall rules — https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules | updated 2026-10-08 | 2026-10-22 | block beats allow, no wildcards |
| E37 | T1 | Windows Filtering Platform — https://learn.microsoft.com/en-us/windows/win32/fwp/about-windows-filtering-platform | updated 2025-03-11 | 2026-10-22 | admin, per app |
| E38 | T1 | AppContainer isolation — https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation | 2025-07-08 | 2026-10-22 | per-container network |
| E39 | T1 | Python venv — https://docs.python.org/3/library/venv.html | undated | 2026-10-22 | Windows redirector `python.exe` |
| E40 | T1 | huggingface_hub env vars — https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables | v2.2.0 docs | 2026-10-22 | offline, telemetry, xet |
| E41 | T1 | huggingface_hub utilities — https://huggingface.co/docs/huggingface_hub/package_reference/utilities | v2.2.0 docs | 2026-10-22 | client factories |
| E42 | T1 | PyPI huggingface_hub — https://pypi.org/pypi/huggingface_hub/2.2.0/json | 2.2.0, 2026-10-08; 1.16.1, 2026-05-21 | 2026-10-22 | httpx family per major |
| E43 | T1 | PyPI hf-xet 1.7.0 — https://pypi.org/pypi/hf-xet/1.7.0/json | 2026-10-06 | 2026-10-22 | Rust extension |
| E44 | T1 | Ultralytics settings — https://docs.ultralytics.com/usage/settings/ | undated | 2026-10-22 | `sync` default True |
| E45 | T1 | PyPI edge-tts — https://pypi.org/pypi/edge-tts/json | 7.3.1 (date not retrieved) | 2026-10-22 | aiohttp |
| E46 | T3 | edge-tts `communicate.py` — https://raw.githubusercontent.com/rany2/edge-tts/master/src/edge_tts/communicate.py | undated | 2026-10-22 | `connector=`, `trust_env=True` |
| E47 | T1 | aiohttp client advanced — https://docs.aiohttp.org/en/stable/client_advanced.html | undated | 2026-10-22 | middlewares, proxy |
| E48 | T4 | LiteLLM telemetry (search result) — https://docs.litellm.ai/docs/observability/telemetry | undated | 2026-10-22 | reported opt-out |
| M1-E | T3 | Local loopback-only probes run with `.venv\Scripts\python -I` (scratch, outside the repo) | 2026-10-22 | 2026-10-22 | proactor unseen by audit hooks; transport catches streamed canary; ~3 µs overhead; refusal wrapped as `APIConnectionError`; venv launcher; installed versions |
