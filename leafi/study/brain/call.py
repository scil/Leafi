"""`brain_call` (ADR-0017 §5; M7 design D4, D7, D8, D11): one walk over the route's tiers and their backends.

The walk follows the route in its order; an outcome changes only which remaining entries come first and which are
skipped (D8):
- `invalid` → the next entry, with the rejection *codes* of D4 (never a value or a validator's message);
- `timeout` → the remaining entries not slower than the one that timed out first, then the others;
- `refused`, `over_budget`, `failed` → the next backend of the same tier, then the next entry;
- an entry whose minimum time no longer fits the moment (minus a margin), or that the budget cannot cover, is
  skipped.
Nothing else runs inside the walk: a timed-out or cancelled backend is marked to reset before its next call, and
the audit rows are written once the walk is over, in `finally`, shielded and bounded (D8). A cancellation ends the
walk at once and is re-raised: the caller's mapping to the latch's status stays M6's.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anyio
from pydantic import ValidationError

from leafi.core import learner_store
from leafi.core.ports import BrainBackend, CallAttempt, CallRecord, Leaf, ModelRequest
from leafi.core.provenance import Provenance, join, of_output
from leafi.core.storage import Store, dumps, now_iso
from leafi.study.brain import routing
from leafi.study.harness import busy

log = logging.getLogger("leafi.brain.call")

AUDIT_S = 0.3
RESET_S = 0.5
MAX_CODES = 8


# ---------------------------------------------------------------- budgets (D7)


@dataclass
class SessionBudget:
    """The session ledger, tier-weighted (ADR-0017 §5.1): every reserved transmission pays its tier's cost."""

    ledger: Any
    tier: str

    def can_cover(self, first: bool) -> bool:
        return self.ledger.can_afford(self.tier)

    def charge(self, first: bool) -> None:
        self.ledger.charge(self.tier)


@dataclass
class CallCountBudget:
    """The post-session allowance (`limits.extract_calls`): counted in calls; the mediator's retry is free."""

    limit: int
    used: int = 0

    def can_cover(self, first: bool) -> bool:
        return not first or self.used < self.limit

    def charge(self, first: bool) -> None:
        if first:
            self.used += 1


# ---------------------------------------------------------------- the call's context and result


@dataclass
class CallContext:
    store: Store
    session_id: int
    learner_id: int | None
    deadline: float                      # monotonic: the moment's end (minus the output reserve) or the session's
    budget_for: Callable[[str], Any]     # tier -> a Budget
    may_use_cloud_text: bool = False     # the learner's `cloud_text_allowed` (answer/judge eligibility, D10)
    activity_id: int | None = None
    prompt_version: str = ""
    pending_audit: list = field(default_factory=list)


@dataclass
class Result:
    value: Any
    tier: str
    degraded: bool
    record: CallRecord
    provenance: Provenance | None = None  # D2: `of_output` over the leaves sent; every use of `value` carries it


@dataclass
class Brain:
    """The tiers the composition root built: tier -> [(backend, model)], the routing table, the locality resolver."""

    tiers: dict[str, list[tuple[BrainBackend, str]]]
    table: dict = field(default_factory=lambda: routing.ROUTES)
    locality: Callable[[BrainBackend, str], str] = lambda backend, model: "cloud"

    def configured(self) -> set[str]:
        return {t for t, entries in self.tiers.items() if entries}

    def eligible(self, tier: str, purpose: str, ctx: CallContext) -> list[tuple[BrainBackend, str]]:
        """ADR-0018 §2: `answer` and `judge` carry the learner's words, so a cloud backend needs the learner's
        `cloud_text_allowed`; the other purposes filter their payload instead (D3)."""
        out = []
        for backend, model in self.tiers.get(tier, []):
            if purpose in ("answer", "judge") and self.locality(backend, model) == "cloud" \
                    and not ctx.may_use_cloud_text:
                continue
            out.append((backend, model))
        return out

    def routable(self, purpose: str, ctx: CallContext, d: str = "normal") -> bool:
        return any(self.eligible(s.tier, purpose, ctx) and ctx.budget_for(s.tier).can_cover(True)
                   for s in routing.route(purpose, d, self.configured(), self.table))


# ---------------------------------------------------------------- D4: rejection codes


def rejection_codes(err: BaseException) -> list[str]:
    """`<code> at <field path>`, from a fixed vocabulary; never a value, a message or an exception string."""
    if not isinstance(err, ValidationError):
        return ["type at ."]
    out = []
    for e in err.errors()[:MAX_CODES]:
        kind = e.get("type", "")
        code = ("missing" if kind == "missing" else "too_long" if kind == "string_too_long"
                else "too_many" if kind == "too_long" else "type")
        path = ".".join(str(p) for p in e.get("loc", ())) or "."
        out.append(f"{code} at {path}")
    return out


# ---------------------------------------------------------------- the walk


MakeRequest = Callable[[str, str, list[str], Any, CallAttempt, float], ModelRequest]


async def brain_call(brain: Brain, ctx: CallContext, purpose: str, make_request: MakeRequest,
                     validate: Callable[[Any], Any], d: str = "normal") -> Result | None:
    """`make_request(model, tier, rejection_lines, budget, attempt, timeout_s)` builds the request; `validate`
    returns the parsed value or raises. Never raises except a cancellation; `None` when the route is exhausted."""
    deadline = min(time.monotonic() + routing.TOTAL_S[purpose], ctx.deadline)
    queue = routing.route(purpose, d, brain.configured(), brain.table)
    records: list[tuple[str, BrainBackend, ModelRequest, CallRecord]] = []
    rejection: list[str] = []
    try:
        while queue:
            step = queue.pop(0)
            for backend, model in brain.eligible(step.tier, purpose, ctx):
                left = deadline - time.monotonic() - routing.SKIP_MARGIN_S
                if left < routing.MIN_TIER_S[step.tier]:
                    break
                budget = ctx.budget_for(step.tier)
                if not budget.can_cover(True):
                    break
                if getattr(backend, "needs_reset", False):
                    with anyio.move_on_after(min(RESET_S, left)):
                        await backend.reset()
                    backend.needs_reset = False
                attempt = CallAttempt()
                timeout = min(routing.PER_CALL_S[purpose][step.tier], deadline - time.monotonic())
                req = make_request(model, step.tier, list(rejection), budget, attempt, timeout)
                started = time.monotonic()
                try:
                    with anyio.fail_after(timeout):
                        rec = await backend.call(req)
                except TimeoutError:
                    backend.needs_reset = True
                    rec = _cut(ctx, attempt, "timeout", started)
                except anyio.get_cancelled_exc_class():
                    backend.needs_reset = True
                    records.append((step.tier, backend, req, _cut(ctx, attempt, "cancelled", started)))
                    raise
                records.append((step.tier, backend, req, rec))
                if rec.outcome == "ok":
                    try:
                        value = validate(rec.value)
                    except (ValidationError, ValueError) as e:
                        rec.outcome, rejection = "invalid", rejection_codes(e)
                        rec.detail = "; ".join(rejection)
                        break  # the next tier, with the codes
                    return Result(value, step.tier, step.degraded, rec,
                                  of_output(leaf.prov for leaf in leaves_of(req)))
                if rec.outcome == "invalid":
                    rejection = [rec.detail or "type at ."]
                    break
                if rec.outcome == "timeout":
                    rank = routing.TIER_RANK[step.tier]
                    queue = ([s for s in queue if routing.TIER_RANK[s.tier] <= rank]
                             + [s for s in queue if routing.TIER_RANK[s.tier] > rank])
                    break
                # refused / over_budget / failed: the next backend of this tier
        return None
    finally:
        with anyio.CancelScope(shield=True), anyio.move_on_after(AUDIT_S):
            await write_audit(ctx, purpose, d, records)


def _cut(ctx: CallContext, attempt: CallAttempt, outcome: str, started: float) -> CallRecord:
    sent = attempt.sent
    transmissions = 0
    if attempt.egress_attempt_id is not None:
        try:
            row = ctx.store.one("SELECT transmitted_attempts FROM egress_log WHERE id=?", (attempt.egress_attempt_id,))
            transmissions = int(row[0]) if row else 0
        except sqlite3.Error:
            pass
    return CallRecord(outcome, sent=sent, model=attempt.model, transmissions=transmissions,
                      latency_ms=int((time.monotonic() - started) * 1000))


# ---------------------------------------------------------------- audit rows (D11, D22)


def leaves_of(req: ModelRequest) -> list[Leaf]:
    return [leaf for t in req.turns for s in t.sections for leaf in s.leaves]


def payload_provenance(leaves: list[Leaf]) -> Provenance:
    """The strongest class among the leaves sent, with every source (the payload holds them as they are)."""
    return join(leaf.prov for leaf in leaves)


def _row(ctx: CallContext, purpose: str, d: str, tier: str, backend: BrainBackend, req: ModelRequest,
         rec: CallRecord) -> dict:
    leaves = leaves_of(req)
    pay, resp = payload_provenance(leaves), of_output(leaf.prov for leaf in leaves)
    pc, ps = learner_store.prov(pay.cls, pay.sources)
    rc, rs = learner_store.prov(resp.cls, resp.sources)
    return dict(session_id=ctx.session_id, activity_id=ctx.activity_id, purpose=purpose, difficulty=d, tier=tier,
                backend=getattr(backend, "name", "?"), endpoint_host=getattr(backend, "host", None),
                model=rec.model or req.model, effective_provider=rec.provider, effective_model=rec.model,
                prompt_version=ctx.prompt_version, payload=dumps(rec.sent if rec.sent is not None else {}),
                payload_provenance_class=pc, payload_source_learners=ps, response=rec.received,
                response_provenance_class=rc, response_source_learners=rs, latency_ms=rec.latency_ms,
                transmitted_attempts=rec.transmissions, tokens_in=rec.tokens_in, tokens_out=rec.tokens_out,
                tokens_cached=rec.tokens_cached,
                estimated_cost=routing.estimated_cost(rec.model or req.model, rec.tokens_in, rec.tokens_out,
                                                      rec.tokens_cached),
                outcome=rec.outcome, created_at=now_iso())


def _withheld(row: dict) -> dict:
    """D22's refusal rule for an audit row: the payload's leaves name a learner being forgotten, so the row is
    kept without any text (stricter than re-rendering: a cloud payload held surrogates, a re-render could not
    reproduce them) and the response — a Brain output naming that learner — is dropped, never relabelled."""
    none = learner_store.prov("system")
    return {**row, "payload": json.dumps({"withheld": "a source learner is being forgotten"}),
            "payload_provenance_class": none[0], "payload_source_learners": none[1], "response": None,
            "response_provenance_class": none[0], "response_source_learners": none[1]}


def _insert(store: Store, row: dict) -> None:
    try:
        learner_store.insert_named(store, "brain_calls", **row)
    except learner_store.LearnerUnavailable:
        log.info("brain_calls row written without its text: a source learner is being forgotten")
        learner_store.insert_named(store, "brain_calls", **_withheld(row))


async def write_audit(ctx: CallContext, purpose: str, d: str, records) -> None:
    """Rows go into `pending_audit` first and leave it only once written, so a busy store or the bounded scope
    cutting this write keeps them for the next write or `finalize`."""
    ctx.pending_audit.extend(_row(ctx, purpose, d, tier, backend, req, rec) for tier, backend, req, rec in records)
    while ctx.pending_audit:
        row = ctx.pending_audit[0]
        try:
            await busy.retry(lambda r=row: _insert(ctx.store, r), limit_s=AUDIT_S)
        except busy.StoreBusy:
            return
        ctx.pending_audit.pop(0)


def flush_audit(ctx: CallContext) -> None:
    """At `finalize`: the rows a busy store kept back (no awaiting)."""
    while ctx.pending_audit:
        _insert(ctx.store, ctx.pending_audit[0])
        ctx.pending_audit.pop(0)
