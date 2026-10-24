"""Construction's `generate` (ADR-0017 §3.3; M7 design D14): one call per (boundary, kind, selection).

A `brain`-owned kind is built from one `generate` call whose result is cached in `s.boundary.content` with the
epoch it was made under, so a re-offer, a silence re-ask or `first_constructible` walking past the same kind reuses
it; a changed epoch clears the cache (a Reobserve). A failed generation is cached too: the same selection is not
asked again at this boundary. Every call of a boundary — `decide` and each `generate` — shares the boundary's one
`next_activity` moment; once it is spent a `brain`-owned kind is refused without a call, so the default chain's
`code`-owned steps remain.

Each kind registers a `Generator` (D15): `sections(s, sel)` builds what the request carries, `model` is its output
schema, and `check(s, sel, value)` binds the references and returns the content or a `Rejected`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from leafi.core.ports import SYSTEM, Provenance, Section
from leafi.privacy import settings as privacy_settings
from leafi.study.brain import call as bc
from leafi.study.brain import prompts, routing
from leafi.study.brain.filler import with_filler
from leafi.study.harness.state import Rejected


@dataclass(frozen=True)
class Generator:
    model: type                                          # the kind's Pydantic output schema (D15)
    sections: Callable[[Any, dict], tuple[Section, ...] | Rejected]
    check: Callable[[Any, dict, Any], dict | Rejected]   # reference binding, answerability (D15)
    difficulty: Callable[[Any, dict], str] = lambda s, sel: "normal"


GENERATORS: dict[str, Generator] = {}


@dataclass(frozen=True)
class Content:
    """Generated content with the provenance its writers store and its lines are spoken with (D2, D15)."""

    value: dict
    provenance: Provenance = SYSTEM
    degraded: bool = False


def context(s, deadline: float, *, activity_id: int | None = None) -> bc.CallContext:
    """The session's `CallContext` for one call: its ledger, its learner's `cloud.text` (answer/judge
    eligibility, D10), the session's audit backlog."""
    privacy = privacy_settings.read(s.store, s.learner_id)
    return bc.CallContext(store=s.store, session_id=s.session_id, learner_id=s.learner_id, deadline=deadline,
                          budget_for=lambda tier: bc.SessionBudget(s.ledger, tier),
                          may_use_cloud_text=privacy.cloud_text_allowed, activity_id=activity_id,
                          prompt_version=prompts.PROMPT_VERSION, pending_audit=s.pending_audit_brain)


def moment(s) -> float:
    """The boundary's `next_activity` moment (monotonic), started by its first Brain call and shared by all."""
    b = s.boundary
    if b.moment is None:
        b.moment = time.monotonic() + routing.moment_s("next_activity", s.mouth)
    return b.moment


def spent(deadline: float) -> bool:
    """No tier fits what is left of the moment (D8's skip rule, for every tier at once)."""
    return deadline - time.monotonic() - routing.SKIP_MARGIN_S < min(routing.MIN_TIER_S.values())


def routable(s, purpose: str) -> bool:
    """D10: some tier of the route has an eligible backend the ledger can afford."""
    if s.brain is None:
        return False
    return s.brain.routable(purpose, context(s, time.monotonic() + routing.TOTAL_S[purpose]))


async def boundary_wait(s, call):
    """A Brain wait at a boundary (D12, D21): inside `controls_only` with the filler. A page turned meanwhile is
    the pending page and the epoch moves on, so negotiate re-observes; a skip is dropped (no offer was heard)."""
    io = s.talk
    if not hasattr(io, "controls_only"):  # a scripted Talk in unit tests
        return await call
    async with io.controls_only(("wait", s.latch.epoch.turn_id)) as taken:
        result = await with_filler(call, show=io.hub.show, say=io.say if s.mouth == "pc" else None, epoch=s.epoch)
    for item in taken:
        if item.kind == "page" and s.on_page is not None:
            s.on_page(item.u)
            s.latch.epoch.bump()
    return result


def _key(kind: str, sel: dict) -> tuple[str, str]:
    return kind, json.dumps(sel, sort_keys=True, default=str)


async def content(s, kind: str, sel: dict) -> Content | Rejected:
    """The cached content of (kind, selection) at this boundary, or one `generate` call to make it."""
    b = s.boundary
    epoch = s.epoch()
    if b.content_epoch != epoch:
        b.content.clear()
        b.content_epoch = epoch
    key = _key(kind, sel)
    if key in b.content:
        return b.content[key]
    gen = GENERATORS.get(kind)
    deadline = moment(s)
    if gen is None or s.brain is None or spent(deadline):
        return Rejected("not available now")  # not cached: a later boundary may have time or a Brain
    out = await _generate(s, gen, kind, sel, deadline)
    if s.epoch() == epoch:  # content made under an older epoch is never kept (ADR-0017 §1)
        b.content[key] = out
    return out


async def _generate(s, gen: Generator, kind: str, sel: dict, deadline: float) -> Content | Rejected:
    sections = gen.sections(s, sel)
    if isinstance(sections, Rejected):
        return sections
    make = prompts.generate_request(kind, sections, gen.model, policy=prompts.policy_text(
        autonomy=s.autonomy, age_band=None), learner_id=s.learner_id, session_id=s.session_id)
    result = await boundary_wait(s, bc.brain_call(s.brain, context(s, deadline), "generate", make,
                                                  gen.model.model_validate, gen.difficulty(s, sel)))
    if result is None:
        return Rejected("not available now")
    checked = gen.check(s, sel, result.value)
    if isinstance(checked, Rejected):
        return checked
    return Content(checked, result.provenance or SYSTEM, result.degraded)
