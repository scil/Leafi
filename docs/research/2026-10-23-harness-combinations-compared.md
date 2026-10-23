# Harness prototypes compared: Combination 1 (thin) vs Combination 2 (library-backed)

Checked: 2026-10-23. Teaching material for the owner (plan M2 follow-up; owner decision 2026-10-23: keep both prototypes as study material, Combination 1 is the default for M6/M7). It reads the code in `scripts/prototypes/harness/` (`common.py`, `comb1.py`, `comb2.py`, `bench.py`) mechanism by mechanism and explains the numbers in [`2026-10-22-harness-libraries.md`](2026-10-22-harness-libraries.md) §7.1. The loop both implement is ADR-0017 §1–§2 (`docs/adr/0017-ai-led-study-session.md`).

Method. Everything below was read from the prototype files and from the libraries' own source in the prototype venv (tenacity 9.2.1, stamina 26.1.0, apache-burr 0.43.0, pydantic-ai-slim 2.59.0, anyio 4.14.2, anthropic 1.17.0 on httpx2, SQLite 3.54.1). Numbers come from `bench.py` (rerun today), `cProfile` runs of the same workloads, and three small experiments kept outside the repository (Burr after a stop, a decision timeout in each combination, commit cost per SQLite journal mode). Claims marked *(inferred)* were reasoned from code, not measured.

One bug was found and fixed while writing this: Combination 1 raised `UnboundLocalError` when a Brain decision timed out (§2.1, commit `6c00f56`). Combination 1 is now 112 counted lines instead of 111.

## 0. Vocabulary used below

- **Control flow**: the order in which code runs, and the code that decides that order. "Where control flow lives" asks which file you read to know what runs next.
- **Orchestration**: the code that picks and starts the next step of a multi-step process (here: decide → negotiate → run an activity → decide again).
- **Cancel scope** (anyio): a `with` block that can be cancelled from outside; once cancelled, every `await` inside it raises the cancellation exception. anyio's scopes are **level-triggered**: the cancellation is raised again at *every* later `await` inside the scope until the scope exits, so a library that swallows it once is cancelled again at its next `await`. Plain asyncio cancellation is **edge-triggered**: raised once.
- **Shield**: a cancel scope with `shield=True` that ignores cancellation from outer scopes; used for cleanup that must run after a cancel.
- **Latch**: a value that can be set once and never unset. `Session.terminal` is the session's latch: the first terminal reason wins (`common.terminate`).
- **Absolute deadline**: a point on the clock ("stop at 12:00:05.300"). **Relative timeout**: a length of time counted from when some code starts ("stop 0.3 s after I start"). Two relative timeouts nested inside one another do not add up to one absolute deadline unless each is recomputed from the clock.
- **Transaction boundary**: the `BEGIN … COMMIT` around a group of writes; everything inside commits or rolls back together, nothing across two boundaries does.
- **Dual write**: writing one logical fact into two stores (two tables on two connections, two databases) without one transaction around both. A crash between the two writes leaves them disagreeing.
- **Idempotent**: running it twice has the same effect as running it once.
- **At-least-once / at-most-once**: after a crash, a step may run again (at-least-once) or is never repeated but may be lost (at-most-once). Exactly-once needs the step's effects and the "step done" mark in one transaction.
- **Jitter**: a random addition to a retry's wait, so many clients do not retry at the same instant.
- **`ExceptionGroup` / `except*`** (Python 3.11, PEP 654): a task group that ends with errors raises one `ExceptionGroup` holding all of them; `except* T:` handles the members of type `T` and lets the rest propagate.
- **fsync**: asking the operating system to push a file's data to the disk before returning; the slow part of a durable commit.
- **WAL / rollback journal**: SQLite's two ways of making commits atomic. The **rollback journal** (`journal_mode=delete`) copies old pages into a side file and deletes it at commit; **WAL** (write-ahead log) appends new pages to a log. `synchronous=FULL` fsyncs at every commit; `synchronous=NORMAL` in WAL fsyncs only at checkpoints, so the last commits can be lost at a power cut but the file is never corrupted.

## 1. The shared ground (`common.py`)

Both combinations import the same latch, activities, recovery and mock Claude, so only three mechanisms differ: the session loop, retries, and the LLM call. Know the shared pieces first, because both designs lean on them.

```python
def terminate(s: Session, reason: str) -> None:
    if s.terminal is None:          # monotonic latch: the first reason wins
        s.terminal = reason
        ...
        if reason == "lease_lost":
            s.lease_held = False    # say() checks this before cancelling anything
        if s.scope is not None:
            s.scope.cancel()        # level-triggered: every await inside now raises
```

- **The latch is set before anything is cancelled.** Every `except` that catches the cancellation can read `s.terminal` and map it to a status (`map_status`). This is ADR-0017 §1's "setting `s.terminal` is the only way to interrupt the session".
- **The deadline is a watcher task, not a scope deadline.** `deadline_watcher` sleeps until `s.hard_deadline`, then calls `terminate(s, "time_up_session")`. A scope with its own `deadline=` would cancel without setting the latch, and every handler would have to guess why.
- **`checkpoint(s)` is the cooperative path.** Cancellation only lands at an `await`; code that runs between awaits calls `checkpoint(s)`, which raises `Terminal` when the latch is set. Two exceptions therefore mean "the session is ending": the scope's cancellation (a `BaseException`) and `Terminal` (an `Exception`). Both handlers below catch the pair.
- **`spawn` sets the latch before a child's error propagates**, so the task group's cancellation of the body always finds a reason.
- **`Store.tx()` is the transaction boundary**: `BEGIN IMMEDIATE` takes the write lock at the start (instead of at the first write), so a busy store fails before any work is done. `read_listen` writes the three candidates *and* their ledger row in one `tx()` (ADR-0017 §7.2): effects and the record that they happened cannot disagree.
- **`recover()` is startup recovery** (ADR-0017 §8.5): `running` activities become `interrupted`, open cycles close, unpractised candidates settle. It reads only Leafi's own tables.

## 2. Session loop and orchestration

### 2.1 Combination 1: a `while` loop you can read top to bottom

```python
async def run_session(s, brain, decision_s=5.0):
    s.id = start_session(s.store)
    try:
        with anyio.CancelScope() as s.scope:
            async with anyio.create_task_group() as s.tg:
                spawn(s, deadline_watcher, s)
                try:
                    while True:
                        checkpoint(s)
                        deadline = min(time.monotonic() + decision_s, s.hard_deadline)
                        d = None  # move_on_after skips the assignment when the decision times out
                        with anyio.move_on_after(deadline - time.monotonic()):
                            d = await brain.decide(observation(s), deadline)
                        kind, by = (d.activity, "brain") if d and d.activity in MENU else ("end", "default")
                        kind = await negotiate(s, kind)
                        if kind == "end":
                            break
                        if await run_activity(s, kind, by) not in ("completed", "page_turned"):
                            break
                finally:
                    s.tg.cancel_scope.cancel()
    except* Terminal:
        pass
    reason = s.terminal or "end"
    finalize(s, reason)
    with anyio.move_on_after(2, shield=True):
        deliver(s)
    return reason
```

Read it as three nested layers.

1. **The cancel scope** (`s.scope`) is what `terminate` cancels. When a scope that was cancelled exits, it swallows its own cancellation exception, so after the `with` block the code continues normally to `finalize`.
2. **The task group** holds the deadline watcher. `finally: s.tg.cancel_scope.cancel()` stops the watcher when the loop ends normally; without it the task group would wait for the watcher's sleep to finish (up to the whole session length).
3. **The loop body.** A `Terminal` raised by `checkpoint` inside it leaves the task group wrapped in an `ExceptionGroup`; `except* Terminal` outside the cancel scope unwraps it. It must sit outside the task group: inside, the exception is still a bare `Terminal`, outside it is a group.

Where things live:

- **Control flow** is the `while` loop: one file, one function.
- **State** is the `Session` object in memory plus Leafi's tables on disk. There is no third copy.
- **Persistence** is in the domain functions (`start_activity`, `read_listen`, `finish_activity`), each a transaction that writes facts, not "where the loop was".
- **Cancellation** travels: `terminate` → `s.scope.cancel()` → the next `await` inside `listen` raises → `run_activity` catches `(Terminal, cancelled)`, maps the status, and its `finally` runs `finish_activity` → the exception re-raises out of the task group → the scope swallows it → `finalize`.

```python
async def run_activity(s, kind, decided_by):
    aid = start_activity(s, kind, decided_by)
    status = "internal_error"
    try:
        status = await ACTIVITIES[kind](s, aid)
    except (Terminal, anyio.get_cancelled_exc_class()):
        status = map_status(s)
        raise
    finally:
        finish_activity(s, aid, status)  # never left `running`
    return status
```

One idiom to notice: `finish_activity` is **synchronous**. Cancellation is delivered only at `await`, so a synchronous SQLite write in a `finally` always runs to the end even inside a cancelled scope. If it were `await finish_activity(...)`, the cancelled scope would raise at that `await` and the row would stay `running` unless the call were shielded. Comb2's Burr hits exactly that problem (§2.3).

**The bug that was fixed.** `anyio.move_on_after` cancels the block *and then continues after it*. When the Brain call ran past `decision_s`, the assignment `d = await …` never happened. On the first decision that raised `UnboundLocalError` inside the task group (measured: `ExceptionGroup('unhandled errors in a TaskGroup', [UnboundLocalError(...)])`, and `finalize` never ran); on a later decision it would silently have reused the *previous* decision. Comb2 already had `d = None`. Rule: **a variable assigned inside `move_on_after` must be given a value before the block.** `bench.py` never reached the path: its hung-Brain test stops the whole session, it never lets one decision time out.

### 2.2 Combination 2: Burr actions and transitions

```python
@action(reads=[], writes=["next", "decided_by"])
async def decide(state: State) -> State:
    checkpoint(s)
    ...
    return state.update(next=await negotiate(s, kind), decided_by=by)

@action(reads=["next", "decided_by"], writes=["last_status"])
async def run(state: State) -> State:
    aid = start_activity(s, state["next"], state["decided_by"])
    ...
    return state.update(last_status=status)

ApplicationBuilder()
    .with_actions(decide=decide, run=run, done=done)
    .with_transitions(("decide", "done", expr("next == 'end'")), ("decide", "run", default),
                      ("run", "decide", expr("last_status in ('completed', 'page_turned')")),
                      ("run", "done", default))
    .with_state_persister(persister)
```

- **Control flow** is split between the actions (what each step does) and the transition table (what runs next). The `while` loop moved into Burr's `Application.arun`, which repeatedly calls `_astep`: pick the next action from the transitions, run it, save state, repeat.
- **State** now has three homes: Burr's `State` (`next`, `decided_by`, `last_status`), the `Session` object the actions close over (`s`, captured by the `build_actions` closure, with the cycle, latch, skips and script), and Leafi's tables. Burr persists only the first, which holds the least.
- **Persistence**: Burr's `AsyncSQLitePersister` appends one row per action to `burr_state` on its own `aiosqlite` connection (a second writer into the same file), then commits (`b_aiosqlite.py`, `save`: `INSERT … ; await self.connection.commit()`). The table is append-only: it grows by two rows per decision.
- **Cancellation** passes through Burr's `_astep` (`burr/core/application.py`):

```python
try:
    ...
    result, new_state = await _arun_single_step_action(next_action, self._state, inputs=action_inputs)
    ...
except Exception as e:
    exc = e
    logger.exception(...)      # a normal stop (Terminal) is logged as an error with a traceback
    raise e
finally:
    await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
        "post_run_step", ..., state=new_state, exception=exc, ...)   # → persister.save(...)
```

Two consequences, one measured and one read:

- **A cancelled action is not saved.** The cancellation is a `BaseException`, so `except Exception` skips it and `finally` runs `await persister.save(...)` inside the still-cancelled scope; level-triggered cancellation raises at that `await` and the row is never written. Measured: after a stop during `read_listen`, `burr_state` holds one row, `(0, 'decide', 'completed', {"next": "read_listen", …})`. Burr's table now says "the next step is `run`" after a clean stop, not only after a crash.
- **A `Terminal` is saved as `failed`.** `Terminal` is an `Exception`, so Burr logs it with a traceback and saves `status="failed"`; on resume, `initialize_from` restarts *at the failed action* (`application.py`: `else: self.start = last_position`). Either way, a stopped activity is the one Burr would run again.

### 2.3 Why Burr's resume re-ran a side-effecting activity and Combination 1's did not

```mermaid
sequenceDiagram
    participant Loop as decide / run
    participant Leafi as Leafi tables (Store.c)
    participant Burr as burr_state (aiosqlite)
    Loop->>Burr: save(decide, completed, next=read_listen)
    Loop->>Leafi: tx: INSERT activity (running)
    Loop->>Leafi: tx: INSERT 3 miscues + ledger row
    Note over Loop: kill point "after_effects" (TerminateProcess)
    Loop--xBurr: save(run, completed) never happens
    Note over Leafi,Burr: restart
    Leafi->>Leafi: recover(): activity interrupted, cycle closed, candidates settled
    Burr->>Loop: initialize_from(resume_at_next_action) → next action = run
    Loop->>Leafi: run read_listen again: new activity, 3 new miscues, 1 new ledger row
```

The root cause is a **dual write across two transaction boundaries**. `read_listen`'s effects commit on Leafi's connection; Burr's "run is done" row commits later on another connection. A kill between the two commits leaves Leafi saying "done" and Burr saying "not done". Burr's resume trusts its own table, so execution is **at-least-once**, and `read_listen` is not idempotent.

Combination 1 has no "resume at the next step" at all. Its only record is Leafi's tables, where effects and ledger share one transaction; on restart `recover()` closes what was open and the learner is asked "continue from page A?" (ADR-0017 §8.5). That is **at-most-once plus asking a human**, the right choice for a spoken session with a child: re-running a paused question after a crash would replay speech the child already heard.

Two details of the bench's measurement worth knowing:

- `duplicate_ledger` groups by `(activity_id, item)`. The re-run gets a *new* `activity_id`, so the check reports 0; the duplicate is semantic (the same page read recorded twice), visible only as `rerun_new_rows: 1`.
- `rerun_new_rows` counts `practices` and `ledger` only. By reading `read_listen` *(inferred)*, the re-run also inserted three new `candidate` miscues, into the cycle that `recover()` had already closed (`_burr_resume` sets `s.cycle_id` to the newest cycle). Nobody settles candidates in a closed cycle, so they would stay `candidate` for ever.

How Burr could be made safe here, so you can judge the cost: make every action idempotent (look up by a natural key before writing), or write Burr's state row in the *same* transaction as the action's effects (a custom persister on Leafi's connection called from inside the action, which defeats Burr's own `post_run_step`), or never resume (`resume_at_next_action=False`), at which point the persister is only a log.

### 2.4 Lines and readability

The counted lines are close (112 vs 107), but they are not the same kind of lines. Comb1's loop is about 15 lines in one function. Comb2 spends about 35 lines on two action functions, a `done` action, a transition table and a builder with two branches (fresh and resume), and its `decide` action mixes Burr state with closure state. To learn what happens after `practise_errors` returns `page_turned`, in comb1 you read the `if` in the loop; in comb2 you read the transition expressions and know Burr's rule that the first matching transition wins.

What Burr does give, and comb1 lacks: an explicit, declarative **transition table**. It is a list of data that a test or a diagram can read, and its tracker (opt-in, writes `~/.burr`) can replay state over time.

## 3. Retries

### 3.1 Combination 1: `call_with_retry`, about 15 lines

```python
async def call_with_retry(fn, deadline: float, attempts: int = 3, min_attempt_s: float = 0.5):
    wait = tenacity.wait_exponential_jitter(initial=0.2, max=2.0)
    for n in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as e:
            if not _retryable(e) or n == attempts:
                raise
            after = getattr(getattr(e, "response", None), "headers", {}).get("retry-after")
            delay = float(after) if after else wait(SimpleNamespace(attempt_number=n))
            if time.monotonic() + delay + min_attempt_s >= deadline:
                raise BudgetExhausted(f"retry needs {delay:.1f}s") from e
            await anyio.sleep(delay)
```

- **The deadline is absolute.** The check `now + delay + min_attempt_s >= deadline` asks the question that matters: "after I sleep, will there be time for one more useful attempt?" If not, give up *now* and leave the remaining time to the next tier. That is why the 0.3 s-budget test sends 1 request and returns in 0 ms.
- **`except Exception` does not catch cancellation** (a `BaseException` in both asyncio and anyio), so a deadline or stop that arrives during `anyio.sleep(delay)` ends the retry loop at once (research P-B4).
- **`_retryable`** uses the SDK's own classes: `APIStatusError` with 408, 409, 429 or ≥ 500, `APIConnectionError`, and honours `x-should-retry: false`. The SDK itself is built with `max_retries=0` (`bench.client`), so this loop is the **single retry owner**: requests do not multiply (research finding 0.2).
- **Only tenacity's wait object is used.** `wait(SimpleNamespace(attempt_number=n))` is **duck typing**: a wait strategy is a callable that reads `retry_state.attempt_number`, so any object with that attribute works. It saves writing the backoff formula; it also depends on tenacity reading no other attribute, which a test should pin.

### 3.2 Combination 2: stamina's `AsyncRetryingCaller`

```python
caller = stamina.AsyncRetryingCaller(attempts=3, timeout=max(0.0, deadline - time.monotonic()),
                                     wait_initial=0.2, wait_max=2.0).on(_retryable)
return (await caller(self.agent.run, obs)).output
```

stamina turns `timeout` into tenacity's `stop_after_delay` (`stamina/_core.py`, `_make_stop`), and tenacity 9.2.1's check is:

```python
return retry_state.seconds_since_start >= self.max_delay      # stop_after_delay
```

It looks only at time already spent, never at the sleep about to start. With 0.3 s of budget the first 503 comes back at about 0 s, `0 < 0.3`, so stamina sleeps. The sleep is `min(wait_max, wait_initial * 2**(n-1) + uniform(0, wait_jitter))` (`_compute_backoff`), and comb2 did not set `wait_jitter`, whose default is **1.0 s**. So the first wait is anywhere from 0.2 to 1.2 s, and the second attempt starts after the budget has gone. That is why the bench's elapsed time varies between runs: 421 ms in §7.1, 953 ms and 1204 ms today. Inside a real session the outer `move_on_after` would cut the attempt, but the remaining budget is already spent sleeping, and nothing is left for a fallback tier.

tenacity has the right primitive, `stop_before_delay`, which adds `retry_state.upcoming_sleep`; stamina does not expose it. Even that one lacks `min_attempt_s`: "I can start an attempt" is not "I can finish one".

Retries and fallback also interact badly in comb2:

- With one tier, `agent.run` raises `ModelHTTPError` and stamina retries it (the 503-then-200 test sends 2 requests, like comb1).
- With two tiers, `FallbackModel` catches the primary's error and moves on at once; if all tiers fail it raises `FallbackExceptionGroup`, which `_retryable` does not match. So the primary is tried **once** (measured: primary 1 request, secondary 1), and a stamina retry, when it does happen, reruns the *whole* chain. A retry owner can only sit around the chain, never per tier.

### 3.3 The idiom underneath: who owns the clock

A **relative** timeout composes badly: each layer measures from its own start, and the sum overruns. An **absolute** deadline passed down (`deadline`, then `min(now + PER_CALL_S, deadline - now)`, as in ADR-0017 §5) composes: every layer asks the same clock the same question. anyio's `move_on_at`/`fail_at` (anyio ≥ 4.15; the venv has 4.14.2) and `CancelScope(deadline=…)` take absolute times; prefer them over `move_on_after(deadline - now)`, which is the same thing computed by hand (and `move_on_after` starts its timer when *called*, not when entered).

## 4. LLM calls

### 4.1 Combination 1: `Brain` over the raw SDK

```python
async def _once(self, client, model, obs) -> Decision:
    for _ in range(2):
        msg = await client.messages.create(
            model=model, max_tokens=256, system="Pick the next activity from the menu.",
            messages=[{"role": "user", "content": obs}],
            output_config={"format": {"type": "json_schema", "schema": DECISION_SCHEMA}})
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            return Decision.model_validate_json(text)
        except ValidationError:
            continue
    raise ValueError("invalid output twice")

async def decide(self, obs, deadline) -> Decision | None:
    for client, model in self.tiers:
        try:
            return await call_with_retry(lambda c=client, m=model: self._once(c, m, obs), deadline)
        except Exception:  # cancellation is a BaseException and passes through
            continue
    return None
```

- **Structured output** is the API's JSON-schema mode (`output_config.format`), validated again by pydantic (`model_validate_json`): the model is constrained, the harness still checks.
- **Retry per tier, then fall back**: each tier gets the retry loop, and the next tier gets what is left of the same absolute deadline. This is the cascade ADR-0017 §5 asks for.
- **`lambda c=client, m=model:`** is the **default-argument capture** idiom. A plain `lambda: self._once(client, model, obs)` would read `client` and `model` when called, not when created (Python closures bind late). Here it is called inside the same iteration, so the plain form would also work, but the default-argument form stays correct if the lambda is ever stored or called later.
- **`except Exception: continue`** relies on cancellation not being an `Exception`, as the comment says. It also hides programming errors (a `TypeError` in `_once` looks like "tier failed").

### 4.2 Combination 2: pydantic-ai `Agent` + `FallbackModel`

```python
models = [AnthropicModel(m, provider=AnthropicProvider(anthropic_client=c)) for c, m in tiers]
self.agent = Agent(FallbackModel(*models) if len(models) > 1 else models[0], output_type=Decision,
                   instructions="Pick the next activity from the menu.", retries=1)
```

- **Leafi still builds the SDK clients** (`anthropic_client=c`, `max_retries=0`, the mock transport), so the egress seam is unchanged and the canary test passes.
- **Output** is a *tool call*: pydantic-ai's default output mode turns `Decision` into a tool named for the output, and the model "calls" it (the mock answers with `tool_use` when `tools` is present). The request goes to the **beta** Messages endpoint (`anthropic/resources/beta/messages/messages.py` in the profile).
- **`retries=1`** is the output-validation retry: on invalid output pydantic-ai sends the validation error back to the model as a retry prompt. That is better than comb1's re-ask, which resends the identical request and so only resamples.
- **`FallbackModel.request`** (`pydantic_ai/models/fallback.py`): for each model, `try: response = await model.request(...) except Exception as exc: if await self._should_fallback(exc): …; continue` and otherwise re-raise. The default `fallback_on` is `(ModelAPIError,)`, so it falls back on the first API error, with no per-model retry, and not on bad output (a validation failure happens later, in the agent graph). It records each failed attempt with its duration in the response's `failed_attempts`, and raises a `FallbackExceptionGroup` when all fail.

## 5. Efficiency: where 10.6 ms vs 25.6 ms and 0.28 ms vs 2.15 ms come from

### 5.1 Per decision (200 mocked decisions, the "noop" activity)

Rerun today: comb1 10.3 / 12.0 ms, comb2 26.9 / 35.7 ms (p50 / p95). The cProfile of comb1's 200 decisions: 2.34 s total, of which **2.00 s is `sqlite3.Connection.execute`**, spread over 1,408 calls; the LLM layer is 0.26 s. Each decision makes two commits (`start_activity`, `finish_activity`), and a commit is where the time goes:

| SQLite mode (one small `BEGIN IMMEDIATE; INSERT; COMMIT`, this PC) | p50 | p95 |
|---|---|---|
| rollback journal, `synchronous=FULL` (the prototype's `Store`, SQLite's default) | 5.04 ms | 6.19 ms |
| WAL, `synchronous=FULL` (production `leafi.core.storage.Store` on SQLite 3.54.1, ADR-0019) | 1.63 ms | 1.99 ms |
| WAL, `synchronous=NORMAL` | 0.01 ms | 0.02 ms |

So comb1's 10.3 ms is two fsync-bound commits at 5 ms each. Comb2 adds:

- **Two more commits per decision**: Burr saves after `decide` and after `run`, on its own connection (≈ 10 ms).
- **The LLM layer**: 2.2 ms instead of 0.3 ms (§5.2).
- **Thread hops**: `aiosqlite` runs every statement on a worker thread and wakes the event loop when it finishes. The profile shows 10,481 event-loop iterations for comb2 against 12 for comb1, and 1.2 s inside the Windows proactor's `_poll`.

Rerunning the latency test with the shared `Store` switched to WAL (Burr's connection keeps `synchronous=FULL`, a per-connection setting):

| | comb1 p50 / p95 | comb2 p50 / p95 |
|---|---|---|
| rollback journal, FULL (bench as is) | 10.3 / 12.0 ms | 26.9 / 35.7 ms |
| WAL, FULL | 4.0 / 7.1 ms | 9.6 / 12.5 ms |
| WAL, NORMAL on Leafi's connection | **0.5 / 1.1 ms** | 6.5 / 8.6 ms |

Lessons:

- **Measure before optimising.** The harness logic itself costs about 0.2 ms; the rest is the disk. The bench number mostly measured the prototype's journal mode.
- **Fewer commits beats faster code.** One transaction per boundary (finish the old activity and start the next in the same `tx()`) halves comb1's cost in any mode. Each commit is a durability point; ask which ones the design needs.
- **`synchronous=NORMAL` is a decision, not a free speed-up**: the last transactions before a power cut can be lost (never corrupted). ADR-0017 §8.5's recovery already handles a session that ends without its last rows, so it may be acceptable; it is the owner's call.
- **All of this is small beside a model call** (1–3 s). The per-decision overhead did not decide the choice; the budget and resume rows did.

Comb1's profile also shows something to keep in mind for M6: with an instant mock Brain and synchronous SQLite, the whole 200-decision session ran in **12 event-loop iterations**. The coroutine never suspended, so no other task (the deadline watcher, a control event) could run in between. With real network calls this cannot happen, but a loop step that never awaits anything real can starve the loop; an explicit `await anyio.lowlevel.checkpoint()` at the top of the loop guarantees a yield point.

### 5.2 Per LLM call (100 calls against the instant mock)

Rerun today: comb1 0.28 ms (raw SDK 0.27 ms), comb2 2.18 ms (raw SDK 0.35 ms). The profile of 200 calls:

| | function calls per `decide` | what they are |
|---|---|---|
| comb1 | ≈ 2,460 | the SDK: build the request (`_build_request`, header merge, URL parse), the transport, `construct_type` of the response |
| comb2 | ≈ 13,350 | the same SDK work, plus a **pydantic-graph run per request** (user-prompt node, model-request node, call-tools node, end), a run context rebuilt about 42 times by `dataclasses.replace`, 14 anyio task spawns, capability hooks wrapping the event stream, `copy.deepcopy` of settings, a usage price lookup in `genai_prices` (about 124 `is_match` calls per request), and a new tenacity `AsyncRetrying` built by stamina per call |

So comb1's layer is the SDK and nothing else, and comb2's layer is a small agent framework run per call. The raw SDK call is also slower in comb2's run (0.35 vs 0.27 ms) *(inferred: more garbage from pydantic-ai's objects means more garbage-collector work landing on the interleaved raw calls; not investigated)*.

What would make each faster, if it ever mattered:

- **comb1**: nothing in the layer is worth changing; the SDK is the floor. Reuse one `AsyncAnthropic` client per tier (it already does).
- **comb2**: build the stamina caller once per session instead of per call; turn pydantic-ai features off where it has switches for them (instrumentation, usage pricing) *(not verified which exist in 2.59.0)*; or call the model through pydantic-ai's `direct` API, which drops the graph but also the validation retry (research L6). None changes the conclusion.

### 5.3 The cancellation numbers are clock ticks

§7.1 reports 15–16 ms from event to final row, and today's run shows 0 ms for comb1's `lease_lost`. `time.get_clock_info("monotonic")` on this PC: `GetTickCount64()`, **resolution 0.015625 s**. `time.monotonic()` advances in 15.6 ms steps on Windows, so "16 ms" means "the tick changed once" and "0 ms" means "it did not"; the real latency is below what the clock can show. Use `time.perf_counter()` (sub-microsecond) for latency measurements; keep `monotonic` (the event loop's clock) for deadlines.

## 6. Weaknesses and concrete improvements

### 6.1 Combination 1 (the default for M6/M7)

1. **Fixed: `d` unassigned after a decision timeout** (§2.1). Add a test that a Brain call hanging past `decision_s` ends the decision with `decided_by="default"` and the session continues.
2. **No `except* Exception` arm.** ADR-0017 §2's pseudocode has `except* Exception as eg: log_exception(eg); terminate(s, internal_error)` so that `finalize` runs for every `Exception`. The prototype lets an unexpected error escape `run_session`, skipping `finalize` (startup recovery would clean up, but the session ends without a goodbye and with the cycle open until then).
3. **No budget check before the first attempt.** `call_with_retry` checks the deadline only before a *retry*. When tier 1 gives up with `BudgetExhausted`, tier 2 starts with whatever is left, possibly nothing, and is cut by the outer `move_on_after` mid-request (which can leak an httpcore pool slot, research §2). ADR-0017 §5 has `if now >= deadline: return None` before each call; add `if deadline - now < min_attempt_s: raise BudgetExhausted` at the top of each attempt, and reserve time for the later tiers.
4. **`Retry-After` parsing.** `float(after)` raises `ValueError` on the HTTP-date form of the header; that error is not retryable, so the tier is abandoned for a parsing reason. Parse both forms, treat a negative or unparsable value as absent, and also honour `x-should-retry: true` (the SDK's contract: retry even when the status says otherwise).
5. **Errors are swallowed without a trace.** `Brain.decide`'s `except Exception: continue` turns a bug into "fall back to the next tier", then into `None` → "end". Keep the per-tier errors (for example in an `ExceptionGroup`, as pydantic-ai's `FallbackExceptionGroup` does) and write them to `brain_calls` (ADR-0017 §7.2); re-raise errors that are not API errors.
6. **The re-ask does not say what was wrong.** ADR-0017 §5 has `payload.with_rejection(reason)`; `_once` resends the same request. Also, the menu check (`d.activity in MENU`) sits in the loop rather than in the type: build `Decision` with `activity: Literal[...]` from the menu, so both the JSON schema sent to the model and the pydantic check enforce it.
7. **The retry loop retries the whole `_once`.** A 503 on the re-ask reruns the first ask too, and the two `create` calls inside `_once` share no per-call timeout. Retry the single `create`, and validate outside the retry loop.
8. **Duck-typed tenacity.** `wait(SimpleNamespace(attempt_number=n))` works because `wait_exponential_jitter` reads only `attempt_number`. Pin it with a test, or write the five-line formula and drop tenacity (the only new package).
9. **Synchronous SQLite on the event loop.** With `busy_timeout=250` a busy store blocks the whole loop, including the deadline watcher, for up to 250 ms per statement. ADR-0017 §7.3 already specifies 250 ms plus an `anyio.sleep` backoff and `store_busy`; the prototype has the first half only.
10. **One commit per row change.** Merge `finish_activity` of one activity and `start_activity` of the next into one transaction (§5.1).
11. **`deliver` under a shielded `move_on_after` is synchronous**, so the 2 s budget cannot cut it. It becomes real once `deliver` awaits TTS; keep it shielded then.

### 6.2 Combination 2

1. **Relative retry timeout with 1 s default jitter** (§3.2). Set `wait_jitter` explicitly, and wrap the caller in `anyio.move_on_at(deadline - reserve)` so the clock is absolute; or give up on stamina for this.
2. **Retries cannot be per tier** while `FallbackModel` owns the tier loop (§3.2). The fix is a custom `Model` wrapper that retries one inner model, placed inside `FallbackModel`, which is more glue than comb1's whole loop.
3. **Burr is a second source of truth** (§2.3): dual write, at-least-once resume into non-idempotent actions, a stop that leaves Burr pointing at the stopped action, `Terminal` logged as an error, an append-only table that grows two rows per decision, and a second writer connection into `leafi.db` (*inferred* `SQLITE_BUSY` risk under the supervisor, not measured).
4. **State split three ways** (Burr `State`, the closed-over `Session`, Leafi tables). Burr persists the smallest of them.
5. **Silent `except Exception: return None`** in `Brain.decide`, as in comb1.
6. **Noise**: pydantic-ai's stderr banner unless `PYDANTIC_AI_NO_BANNER=1`; stamina's `stamina.retry_scheduled` log lines on every retry (visible at the top of every bench run).

### 6.3 Ideas worth borrowing from Combination 2 into Combination 1

| From | Idea | How in comb1 |
|---|---|---|
| pydantic-ai `retries=1` | Re-ask with the validation error | `payload.with_rejection(str(err))` as ADR-0017 §5 already says |
| pydantic-ai `output_type` | The schema *is* the type | Generate `DECISION_SCHEMA` from the pydantic model (`Decision.model_json_schema()`) with `Literal` menu values, instead of a hand-written dict that can drift |
| `FallbackExceptionGroup`, `failed_attempts` | Keep every tier's failure with its duration | Return them with the result and write each to `brain_calls` (transmitted attempts, latency, outcome) |
| stamina `set_testing()` | One switch makes every backoff zero in tests | A module-level `RETRY_WAIT_SCALE` (0 in tests) instead of patching `anyio.sleep` |
| stamina's retry hook | Every scheduled retry is an event with structured fields | Log `retry_scheduled` with attempt, delay, error class and remaining budget |
| Burr's transition table | The loop's shape as data a test can read | An `ActivityStatus` → next-step table (or python-statemachine, research §4) that a test checks against ADR-0017 §3.1's table |
| Burr's per-step state rows | A replayable history of decisions | ADR-0017 §9's decision replay: write the observation and the decision into Leafi's own table *in the same transaction* as the activity row |

What not to borrow: resuming at the next step. ADR-0017 §8.5's "close and ask" is deliberate.

## 7. Exercises

1. **Clock.** Print `time.get_clock_info` for `monotonic` and `perf_counter`; rerun `bench.cancel` with `perf_counter` timestamps and report the real event-to-final latency.
2. **`move_on_after` trap.** Revert the fix in a scratch copy of `comb1.py`, write the failing test (a `MockClaude(hang=True)` with `decision_s=0.3`), see `UnboundLocalError`, restore the fix, see it pass.
3. **Absolute deadline.** Replace `move_on_after(deadline - time.monotonic())` with an absolute-time scope (`CancelScope(deadline=deadline)` on 4.14, or `move_on_at` after upgrading anyio to ≥ 4.15). Then make the session's hard deadline movable: let the watcher run under `CancelScope(deadline=s.hard_deadline)` and update that scope's `deadline` when a setting changes (`common._post_later` currently has to call `terminate` itself because the watcher's `sleep_until` read the old value).
4. **Budget arithmetic.** Rewrite `call_with_retry` with a check before every attempt and a reserve per remaining tier. Test: 0.3 s budget, two tiers, tier 1 returns 503: tier 1 gets one request, tier 2 still gets one.
5. **stamina fix.** In comb2, set `wait_jitter=0` and wrap the caller in `move_on_at(deadline)`; rerun `bench.retries`. Then explain why the 0.3 s case still sends two requests (hint: `stop_after_delay` vs `stop_before_delay`).
6. **Transaction boundaries.** Move `kill_point("after_effects")` *inside* `read_listen`'s `tx()` (before `COMMIT`) and rerun the kill runs: what does Burr resume to, what does `recover()` find? Then merge `finish_activity` and the next `start_activity` into one transaction and measure the latency change.
7. **Burr after a stop.** Run a comb2 session with `[("event", "stop", 0.3)]`, read `burr_state`, and predict where `initialize_from(resume_at_next_action=True)` would start. Then change the `run` action so that a `Terminal` is caught inside it and returned as a status: what does Burr save now?
8. **Profile.** Run `cProfile` on `bench.latency` for each combination, sort by `tottime`, and find the top three costs yourself; then switch the store to WAL and repeat. Which line of the profile moved?
9. **Typed menu.** Build `Decision` with `activity: Literal[*MENU]`, generate the JSON schema from it, and send it with `output_config`; delete the `in MENU` check and show a mock that answers `"dance"` is rejected and re-asked with the error.
10. **Read a library.** Find where pydantic-ai decides a response is invalid and builds the retry prompt (start from `Agent(retries=…)` in `pydantic_ai/agent/__init__.py`), and write down what it sends back to the model.
