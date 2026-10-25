"""`brain_call`'s walk (ADR-0017 §5; M7 design D4, D7, D8, D11, D22) on a real clock with fake backends. The time
limits are scaled down (the structure of D8's worked example, in tenths of seconds)."""

from __future__ import annotations

import json

import anyio
import pytest

from leafi.core import learner_store
from leafi.core.ports import CallRecord, Leaf, ModelRequest, Section, Turn
from leafi.core.provenance import Provenance
from leafi.core.storage import Store
from leafi.study.brain import call as bc
from leafi.study.brain import routing
from leafi.study.harness.ledger import Ledger, Limits
from tests import seed


class Fake:
    """A backend whose replies are scripted: ("ok", value) | ("sleep", s) | ("invalid", code) | ("failed",)."""

    locality_destination = "anthropic"
    host = "api.example"

    def __init__(self, name: str, script: list) -> None:
        self.name, self.script, self.requests = name, list(script), []
        self.needs_reset = False
        self.resets = 0

    async def call(self, req: ModelRequest) -> CallRecord:
        self.requests.append(req)
        req.attempt.sent, req.attempt.model = {"model": req.model}, req.model
        step = self.script.pop(0)
        if step[0] == "sleep":
            await anyio.sleep(step[1])
            return CallRecord("ok", value={"late": True})
        if step[0] == "ok":
            return CallRecord("ok", value=step[1], sent=req.attempt.sent, received=json.dumps(step[1]),
                              model=req.model, tokens_in=10, tokens_out=5, transmissions=1)
        if step[0] == "invalid":
            return CallRecord("invalid", sent=req.attempt.sent, detail=step[1], model=req.model, transmissions=1)
        return CallRecord("failed", sent=req.attempt.sent, model=req.model, transmissions=1)

    async def reset(self) -> None:
        self.resets += 1


@pytest.fixture
def scaled(monkeypatch):
    monkeypatch.setitem(routing.PER_CALL_S, "decide", {"fast": 0.2, "standard": 0.3, "deep": 0.4})
    monkeypatch.setattr(routing, "MIN_TIER_S", {"fast": 0.1, "standard": 0.2, "deep": 0.4})
    monkeypatch.setattr(routing, "SKIP_MARGIN_S", 0.03)
    monkeypatch.setitem(routing.TOTAL_S, "decide", 5.0)


@pytest.fixture
def ctx(tmp_path):
    store = Store(tmp_path / "leafi.db")
    learner = seed.learner(store, "Ada")
    sid = seed.session(store, None, learner_id=learner)
    ledger = Ledger(store, sid, Limits(brain_calls=40))
    c = bc.CallContext(store=store, session_id=sid, learner_id=learner, deadline=0.0,
                       budget_for=lambda tier: bc.SessionBudget(ledger, tier))
    c.ledger = ledger
    return c


def _req(leaves=(Leaf("page text", Provenance("page")),)):
    def make(model, tier, rejection, budget, attempt, timeout):
        sections = [Section("page", tuple(leaves))]
        if rejection:
            sections.append(Section("rejected", tuple(Leaf(r) for r in rejection)))
        return ModelRequest("decide", model, "system", (Turn("user", tuple(sections)),), {}, 1024, "low", "off",
                            timeout, None, None, budget, attempt)
    return make


def _brain(fast=(), standard=(), deep=()):
    return bc.Brain({"fast": list(fast), "standard": list(standard), "deep": list(deep)})


def _rows(ctx):
    return [tuple(r) for r in ctx.store.all("SELECT tier, outcome FROM brain_calls ORDER BY id")]


async def test_the_worked_example_a_fast_timeout_then_standard_then_deep_skipped(ctx, scaled):
    """D8, scaled: moment 0.5 s; fast times out at 0.2 → 0.27 s left ≥ standard's 0.2 → standard runs and returns
    invalid at ~0.15 s → what is left is below deep's 0.4 → skipped; the default chain decides."""
    import time

    fast, std, deep = (Fake("f", [("sleep", 1.0)]), Fake("s", [("sleep", 0.15)]), Fake("d", [("ok", {})]))
    ctx.deadline = time.monotonic() + 0.5

    def validate(v):
        raise ValueError("invalid")

    got = await bc.brain_call(_brain([(fast, "fm")], [(std, "sm")], [(deep, "dm")]), ctx, "decide", _req(),
                              validate)
    assert got is None and deep.requests == [] and fast.needs_reset
    assert _rows(ctx) == [("fast", "timeout"), ("standard", "invalid")]
    assert ctx.ledger.brain_spent == 0  # fakes reserve nothing: the budget is egress's to charge (D7)


async def test_an_invalid_reply_sends_codes_only_to_the_next_tier(ctx, scaled):
    import time

    ctx.deadline = time.monotonic() + 3
    from leafi.study.brain import schemas

    fast = Fake("f", [("ok", {"activity": {"kind": "dance", "say": "Rocco is my best friend"}, "turn": "t1"})])
    std = Fake("s", [("ok", {"activity": {"kind": "end"}, "has_alternative": False, "alternative": {"kind": "end"},
                             "say_before": "", "rationale": {"evidence": "", "strategy": "", "intention": ""},
                             "records": [], "turn": "t1"})])
    got = await bc.brain_call(_brain([(fast, "fm")], [(std, "sm")]), ctx, "decide", _req(), schemas.parse_decision)
    assert got.tier == "standard" and got.value.activity.kind == "end"
    (second,) = std.requests
    lines = [leaf.value for s in second.turns[0].sections if s.name == "rejected" for leaf in s.leaves]
    assert lines and all(" at " in line for line in lines)
    assert not any("Rocco" in line or "dance" in line for line in lines)  # never a value (D4)


async def test_a_failed_backend_is_followed_by_the_next_backend_of_the_same_tier(ctx, scaled):
    import time

    ctx.deadline = time.monotonic() + 3
    a, b = Fake("a", [("failed",)]), Fake("b", [("ok", {"x": 1})])
    got = await bc.brain_call(_brain([(a, "m1"), (b, "m2")]), ctx, "decide", _req(), lambda v: v)
    assert got.value == {"x": 1} and got.tier == "fast"
    assert _rows(ctx) == [("fast", "failed"), ("fast", "ok")]


async def test_nothing_is_tried_that_the_budget_cannot_cover(ctx, scaled):
    import time

    ctx.deadline = time.monotonic() + 3
    ctx.ledger.limits = Limits(brain_calls=0)
    a = Fake("a", [("ok", {})])
    assert await bc.brain_call(_brain([(a, "m")]), ctx, "decide", _req(), lambda v: v) is None
    assert a.requests == [] and _rows(ctx) == []


async def test_a_cancelled_call_still_leaves_its_row_and_propagates(ctx, scaled):
    import time

    ctx.deadline = time.monotonic() + 3
    a = Fake("a", [("sleep", 5)])
    with anyio.move_on_after(0.1):
        await bc.brain_call(_brain([(a, "m")]), ctx, "decide", _req(), lambda v: v)
    assert _rows(ctx) == [("fast", "cancelled")] and a.needs_reset


async def test_answer_and_judge_may_use_a_cloud_backend_for_any_learner(ctx, scaled):
    """ADR-0021 E6: no `cloud.text` gate on `answer` and `judge`; egress redacts what they carry."""
    import time

    ctx.deadline = time.monotonic() + 3
    a = Fake("a", [("ok", {})])
    brain = _brain([(a, "m")], [(a, "m")])
    assert brain.routable("answer", ctx) and brain.eligible("fast", "judge", ctx) == [(a, "m")]


async def test_an_audit_row_naming_a_forgotten_learner_keeps_no_text(ctx, scaled):
    """D22: the call's leaves cite learner B, who is marked forgetting before the row is written: the row is kept
    (the call happened and was charged) without its payload text and without the response."""
    import time

    ctx.deadline = time.monotonic() + 3
    ben = learner_store.create(ctx.store, "Ben")
    leaves = (Leaf("Ben likes rockets", Provenance("derived_from_learner", (ben,))),)

    class Forgetting(Fake):
        async def call(self, req):
            ctx.store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ben,))
            return await super().call(req)

    got = await bc.brain_call(_brain([(Forgetting("a", [("ok", {"note": "Ben likes rockets"})]), "m")]), ctx,
                              "decide", _req(leaves), lambda v: v)
    assert got is not None
    row = ctx.store.one("SELECT payload, response, payload_source_learners, outcome FROM brain_calls")
    assert "Ben" not in row["payload"] and row["response"] is None and row["payload_source_learners"] == "[]"
    assert row["outcome"] == "ok"


def test_rejection_codes_name_paths_never_values():
    from pydantic import BaseModel, Field, ValidationError

    class M(BaseModel):
        name: str = Field(max_length=3)
        n: int

    with pytest.raises(ValidationError) as e:
        M.model_validate({"name": "Zephyrine", "n": "x"})
    codes = bc.rejection_codes(e.value)
    assert codes == ["too_long at name", "type at n"] and not any("Zephyrine" in c for c in codes)
