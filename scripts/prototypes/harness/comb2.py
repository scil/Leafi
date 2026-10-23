"""Combination 2, "library-backed" (libraries §7): Burr `Application` + `AsyncSQLitePersister` for the loop,
stamina `AsyncRetryingCaller` per call with `timeout=deadline-now`, pydantic-ai `Agent(output_type)` +
`FallbackModel` over Leafi-built SDK clients. Same latch, activities and negotiation as comb1 (shared or
copied), so only the three mechanisms differ. Counted by bench.py as harness code.
"""

from __future__ import annotations

import time

import anthropic
import anyio
import stamina
from burr.core import ApplicationBuilder, State, action, default, expr
from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from common import (ACTIVITIES, Session, Terminal, checkpoint, deadline_watcher, deliver, finalize, finish_activity,
                    listen, map_status, observation, say, spawn, start_activity, start_session, take_skip)

MENU = ("read_listen", "practise_errors", "end")


class Decision(BaseModel):
    activity: str
    reason: str


def _retryable(e: Exception) -> bool:
    return isinstance(e, ModelHTTPError) and (e.status_code in (408, 409, 429) or e.status_code >= 500)


class Brain:
    def __init__(self, tiers: list[tuple[anthropic.AsyncAnthropic, str]]) -> None:
        models = [AnthropicModel(m, provider=AnthropicProvider(anthropic_client=c)) for c, m in tiers]
        self.agent = Agent(FallbackModel(*models) if len(models) > 1 else models[0], output_type=Decision,
                           instructions="Pick the next activity from the menu.", retries=1)

    async def decide(self, obs: str, deadline: float) -> Decision | None:
        caller = stamina.AsyncRetryingCaller(attempts=3, timeout=max(0.0, deadline - time.monotonic()),
                                             wait_initial=0.2, wait_max=2.0).on(_retryable)
        try:
            return (await caller(self.agent.run, obs)).output
        except Exception:
            return None


async def negotiate(s: Session, kind: str) -> str:
    if s.autonomy >= 8 or kind == "end":
        return kind
    silences = 0
    while True:
        say(s, f"Shall we do {kind}?")
        u = await listen(s)
        checkpoint(s)
        if take_skip(s) or u in ("skip", "no"):
            return "end"
        if u == "yes":
            return kind
        silences += 1
        if silences > 1:
            return "end"


def build_actions(s: Session, brain: Brain, decision_s: float):
    @action(reads=[], writes=["next", "decided_by"])
    async def decide(state: State) -> State:
        checkpoint(s)
        deadline = min(time.monotonic() + decision_s, s.hard_deadline)
        d = None
        with anyio.move_on_after(deadline - time.monotonic()):
            d = await brain.decide(observation(s), deadline)
        kind, by = (d.activity, "brain") if d and d.activity in MENU else ("end", "default")
        return state.update(next=await negotiate(s, kind), decided_by=by)

    @action(reads=["next", "decided_by"], writes=["last_status"])
    async def run(state: State) -> State:
        aid = start_activity(s, state["next"], state["decided_by"])
        status = "internal_error"
        try:
            status = await ACTIVITIES[state["next"]](s, aid)
        except (Terminal, anyio.get_cancelled_exc_class()):
            status = map_status(s)
            raise
        finally:
            finish_activity(s, aid, status)
        return state.update(last_status=status)

    @action(reads=[], writes=[])
    async def done(state: State) -> State:
        return state

    return decide, run, done


async def build_app(s: Session, brain: Brain, persister, decision_s: float = 5.0, resume_app: str | None = None):
    decide, run, done = build_actions(s, brain, decision_s)
    b = (ApplicationBuilder()
         .with_actions(decide=decide, run=run, done=done)
         .with_transitions(("decide", "done", expr("next == 'end'")), ("decide", "run", default),
                           ("run", "decide", expr("last_status in ('completed', 'page_turned')")),
                           ("run", "done", default))
         .with_state_persister(persister))
    if resume_app:
        b = b.initialize_from(persister, resume_at_next_action=True, default_state={"next": "end"},
                              default_entrypoint="decide").with_identifiers(app_id=resume_app)
    else:
        b = b.with_state(next="end", decided_by="default", last_status="").with_entrypoint("decide") \
             .with_identifiers(app_id=f"session-{s.id}")
    return await b.abuild()


async def run_session(s: Session, brain: Brain, persister, decision_s: float = 5.0) -> str:
    s.id = start_session(s.store)
    app = await build_app(s, brain, persister, decision_s)
    try:
        with anyio.CancelScope() as s.scope:
            async with anyio.create_task_group() as s.tg:
                spawn(s, deadline_watcher, s)
                try:
                    await app.arun(halt_after=["done"])
                finally:
                    s.tg.cancel_scope.cancel()
    except* Terminal:
        pass
    reason = s.terminal or "end"
    finalize(s, reason)
    with anyio.move_on_after(2, shield=True):
        deliver(s)
    return reason
