"""Combination 1, "thin, own the loop" (libraries §7): hand-written session loop (ADR-0017 §2, cut down),
a ~30-line retry loop with tenacity's wait objects and an absolute deadline, raw `anthropic` + pydantic with
Leafi's own fallback list. Counted by bench.py as harness code.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import anthropic
import anyio
import tenacity
from pydantic import BaseModel, ValidationError

from common import (ACTIVITIES, DECISION_SCHEMA, Session, Terminal, checkpoint, deadline_watcher, deliver, finalize,
                    finish_activity, listen, map_status, observation, say, spawn, start_activity, start_session,
                    take_skip)

RETRY_STATUS = {408, 409, 429}
MENU = ("read_listen", "practise_errors", "end")


class Decision(BaseModel):
    activity: str
    reason: str


class BudgetExhausted(Exception):
    pass


def _retryable(e: Exception) -> bool:
    if isinstance(e, anthropic.APIStatusError):
        if e.response.headers.get("x-should-retry") == "false":
            return False
        return e.status_code in RETRY_STATUS or e.status_code >= 500
    return isinstance(e, anthropic.APIConnectionError)


async def call_with_retry(fn, deadline: float, attempts: int = 3, min_attempt_s: float = 0.5):
    """The only retrier (SDK max_retries=0). Gives up when the next sleep plus one attempt would cross the
    absolute deadline; the caller's cancel scope cuts an attempt in flight."""
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


class Brain:
    """Raw SDK + pydantic; one re-ask on invalid output; Leafi's own ordered fallback across tiers."""

    def __init__(self, tiers: list[tuple[anthropic.AsyncAnthropic, str]]) -> None:
        self.tiers = tiers

    async def _once(self, client: anthropic.AsyncAnthropic, model: str, obs: str) -> Decision:
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

    async def decide(self, obs: str, deadline: float) -> Decision | None:
        for client, model in self.tiers:
            try:
                return await call_with_retry(lambda c=client, m=model: self._once(c, m, obs), deadline)
            except Exception:  # cancellation is a BaseException and passes through
                continue
        return None


async def negotiate(s: Session, kind: str) -> str:
    """ADR-0017 §2.1, only the paths flow step 6 needs: announce from 8, else ask, one silence re-ask."""
    if s.autonomy >= 8 or kind == "end":
        return kind
    silences = 0
    while True:
        say(s, f"Shall we do {kind}?")
        u = await listen(s)
        checkpoint(s)
        if take_skip(s) or u in ("skip", "no"):
            return "end"  # the next candidate in the real chain; the prototype has no other
        if u == "yes":
            return kind
        silences += 1
        if silences > 1:
            return "end"


async def run_activity(s: Session, kind: str, decided_by: str) -> str:
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


async def run_session(s: Session, brain: Brain, decision_s: float = 5.0) -> str:
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
