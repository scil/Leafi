"""`sequence(s, obs, menu)` (ADR-0017 §3.3; M7 design D10, D12, D13, D15): on a Brain-arm boundary, one `decide`
call inside `controls_only` with the filler; the decision becomes the `Spec`s negotiate offers.

Ids are bound (D15): only an id this observation rendered, of the right kind, survives; anything else is dropped.
A decision whose echoed turn is not the observation's, or no decision at all, is recorded on the boundary as
`override = brain_unavailable` and the default chain decides (§9: it stays in the Brain arm).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from leafi.core.ports import SYSTEM, Provenance
from leafi.study import knowledge
from leafi.study.brain import call as bc
from leafi.study.brain import generate, prompts, schemas
from leafi.study.brain.filler import with_filler
from leafi.study.brain.observe import Candidate, Item, ObservationInput, observe
from leafi.study.harness.menu import MENU_ORDER
from leafi.study.harness.state import Spec

log = logging.getLogger("leafi.brain.sequence")


@dataclass
class Proposal:
    """What negotiate reads: the Brain's activity and alternative as specs, its rationale and announcement."""

    activity: Spec | None
    alternative: Spec | None = None
    rationale: str | None = None
    say_before: str | None = None
    records: list = field(default_factory=list)
    provenance: Provenance = SYSTEM  # D2: of the rationale and `say_before` (the call's output provenance)


REOBSERVE_PAGE = "page"  # sequence() saw a page turn during its wait: the boundary re-observes


def gather(s, w, menu: set[str], chain: list[str]) -> ObservationInput:
    """The observation's data from the session and the World (§4)."""
    from leafi.study import coach

    store, learner = s.store, s.learner_id
    sentences, unread = (), None
    if w.state is not None and w.rev is not None:
        sentences = tuple((sid, coach.sentence_text(w.rev.text, w.state, sid)) for sid in w.state.sentence_ids())
        unread = next((sid for sid, _ in sentences if sid not in w.state.completed), None)
    weights = knowledge.word_weights(store, learner)
    difficulties = tuple(sorted(weights.items(), key=lambda kv: -kv[1])[:10])
    cands = ()
    if s.cycle_id is not None:
        cands = tuple(Candidate(r["id"], r["expected"], r["heard"], r["origin"], learner) for r in store.all(
            "SELECT id, expected, heard, origin FROM miscues WHERE cycle_id=? AND status='candidate' ORDER BY id",
            (s.cycle_id,)))
    facts = s.facts()

    def items(ids) -> tuple[Item, ...]:
        if not ids:
            return ()
        marks = ",".join("?" * len(ids))
        return tuple(Item(r["id"], r["key"], r["kind"]) for r in store.all(
            f"SELECT id, key, kind FROM knowledge_items WHERE id IN ({marks}) AND learner_id=?", (*ids, learner)))

    last = store.one("SELECT id, kind, status FROM activities WHERE session_id=? ORDER BY id DESC LIMIT 1",
                     (s.session_id,))
    return ObservationInput(
        page_read_id=w.read_id, sentences=sentences, unread_from=unread, difficulties=difficulties,
        candidates=cands, new_items=items(facts.new_item_candidates), recall_due=items(facts.recall_due),
        cardable=items(facts.cardable_items), menu=tuple(k for k in MENU_ORDER if k in menu),
        default_chain=tuple(chain), last_activity=dict(last) if last else None,
        session={"elapsed_min": round(s.ledger.minutes(), 1), "autonomy": s.autonomy,
                 "brain_units_left": round(s.ledger.limits.brain_calls - s.ledger.brain_spent, 2)},
        turn=s.latch.epoch.turn_id)


def _ids(obs, rendered: list[str], kind: str) -> list[int]:
    out = []
    for rid in rendered:
        hit = obs.ids.get(rid)
        if hit is not None and hit[0] == kind and hit[1] not in out:
            out.append(hit[1])
    return out


def to_spec(spec, obs) -> Spec | None:
    """A decided activity as negotiate's `Spec`, with every id bound to this observation (D15)."""
    k = spec.kind
    if k in ("read_listen", "read_aloud"):
        rng = "rest" if spec.from_sentence == 0 and spec.to_sentence == 0 else \
            {"from": spec.from_sentence, "to": spec.to_sentence}
        return Spec(k, {"page": spec.page, "range": rng}, source="brain")
    if k == "practise_errors":
        return Spec(k, {"candidate_ids": _ids(obs, spec.candidate_ids, "candidate")}, source="brain")
    if k in ("recall_items", "teach_items", "add_cards"):
        return Spec(k, {"item_ids": _ids(obs, spec.item_ids, "item")}, source="brain")
    if k == "quiz":
        return Spec(k, {"evidence_sentence_ids": _ids(obs, spec.evidence_sentence_ids, "sentence")}, source="brain")
    if k == "review_anki":
        return Spec(k, {"max_cards": spec.max_cards}, source="brain")
    if k == "learner_questions":
        return Spec(k, {"max_turns": spec.max_turns}, source="brain")
    if k == "break":
        return Spec(k, {"seconds": spec.seconds}, source="brain")
    return Spec(k, {}, source="brain")


async def sequence(s, w, brain: bc.Brain, menu: set[str], chain: list[str]):
    """One `decide` (§3.3). Returns a Proposal, None (the default chain decides), or REOBSERVE_PAGE."""
    obs = observe(gather(s, w, menu, chain))
    ctx = generate.context(s, generate.moment(s))  # D14: decide and construction share the boundary's moment
    mouth = s.mouth
    policy = prompts.policy_text(autonomy=s.autonomy, age_band=None)
    make = prompts.decide_request(obs.sections, policy=policy, learner_id=s.learner_id, session_id=s.session_id)
    inputs = w.inputs
    owner = ("wait", s.latch.epoch.turn_id)
    async with inputs.controls_only(owner) as taken:
        result = await with_filler(
            bc.brain_call(brain, ctx, "decide", make, schemas.parse_decision),
            show=inputs.hub.show, say=inputs.say if mouth == "pc" else None, epoch=s.epoch)
    for item in taken:  # D21: at a boundary a page turn re-observes; a skip before any offer excludes nothing
        if item.kind == "page" and s.on_page is not None:
            s.on_page(item.u)
            return REOBSERVE_PAGE
    if result is None or result.value.turn != obs.turn:
        s.boundary.override = "brain_unavailable"
        return None
    d = result.value
    rationale = d.rationale.strategy if d.rationale is not None and d.rationale.strategy.strip() else None
    return Proposal(to_spec(d.activity, obs), to_spec(d.alternative, obs) if d.alternative else None,
                    rationale, d.say_before, d.records, result.provenance or SYSTEM)
