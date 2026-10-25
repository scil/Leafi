"""Autonomy and negotiation (ADR-0017 §2.1; the pseudocode is the rule, this is a direct transcription).

Below `bands.argue` an activity starts only on the learner's "yes" to that activity, or because the learner named
it and it was built as named; a silence re-ask repeats the same offer; refused kinds stay excluded for the whole
boundary (also across Reobserve); `end` is never excluded; when offers or candidates run out Leafi waits, and
ends only after a second wait.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from leafi.core.ports import Utterance
from leafi.study import controls
from leafi.study.harness.construct import first_constructible
from leafi.study.harness.menu import other_allowed
from leafi.study.harness.policy import default_chain
from leafi.study.harness.state import Activity, Session, Spec

DESCRIBE = {"review_anki": "review your cards", "read_listen": "read the page", "read_aloud": "listen to me read",
            "practise_errors": "practise a few words", "teach_items": "learn some new words",
            "recall_items": "remember some words", "quiz": "answer a few questions",
            "learner_questions": "ask me questions", "add_cards": "make some cards", "break": "take a short break",
            "end": "finish for today", "wait": "wait a moment"}
# Named choices, spoken or typed (`/read`): a fixed list, never a model (controls.py rule).
NAMES = {"read": "read_listen", "reading": "read_listen", "read the page": "read_listen",
         "read to me": "read_aloud", "read aloud": "read_aloud", "listen": "read_aloud",
         "practise": "practise_errors", "practice": "practise_errors", "practise words": "practise_errors",
         "review": "review_anki", "review cards": "review_anki", "cards": "add_cards", "make cards": "add_cards",
         "break": "break", "take a break": "break", "rest": "break", "questions": "learner_questions",
         "quiz": "quiz", "new words": "teach_items", "remember": "recall_items",
         "end": "end", "finish": "end", "that's all": "end", "bye": "end", "goodbye": "end"}


@dataclass(frozen=True)
class Run:
    activity: Activity


class _Reobserve:
    def __repr__(self) -> str:
        return "Reobserve"


REOBSERVE = _Reobserve()


def describe(a: Activity) -> str:
    return DESCRIBE.get(a.kind, a.kind.replace("_", " "))


def parse_choice(u: Utterance | None) -> str:
    """yes | no | skip | named:<kind> | none | unparsed"""
    if u is None or not u.text.strip():
        return "none"
    ctl = controls.of(u)
    if ctl is not None:
        if ctl.kind in ("yes", "no", "skip"):
            return ctl.kind
        if ctl.kind == "unknown" and ctl.text and ctl.text.lower() in NAMES:
            return "named:" + NAMES[ctl.text.lower()]
    flat = " ".join(u.text.lower().replace("’", "'").strip(" .!?").split())
    for prefix in ("let's ", "lets ", "i want to ", "i'd like to ", "can we "):
        if flat.startswith(prefix):
            flat = flat[len(prefix):]
    if flat in NAMES:
        return "named:" + NAMES[flat]
    return "unparsed"


def learner_spec(s: Session, kind: str) -> Spec:
    from leafi.study.harness.policy import default_selection

    return Spec(kind, default_selection(kind, s.facts()), source="learner")


def end_activity(s: Session) -> Activity:
    return Activity("end", {}, "default")


def wait_activity(s: Session) -> Activity:
    return Activity("wait", {"seconds": int(s.settings["negotiation.wait_s"])}, "default", override="wait")


def wait_or_end(s: Session) -> Run:
    return Run(end_activity(s) if s.previous_boundary_was_wait else wait_activity(s))


def _exclude(s: Session, kind: str) -> None:
    if kind != "end":  # end is never excluded
        s.boundary.excluded.add(kind)


def _brain_line(prop, a: Activity, field: str) -> str | None:
    """The Brain's `field` only for the activity it proposed (M7 design D13). It carries no provenance: TTS routes
    it by content (ADR-0021 E6, E7)."""
    proposed = getattr(prop, "activity", None) if prop else None
    text = getattr(prop, field, None) if proposed is not None and proposed.kind == a.kind else None
    return text or None


def rationale_line(prop, a: Activity) -> str:
    """The Brain's reason for the activity it proposed; any other offer gets the static line."""
    return _brain_line(prop, a, "rationale") or f"I think we should {describe(a)} next."


def announcement(prop, a: Activity) -> str:
    """At `bands.announce` (D13): the Brain's `say_before` when `a` is its activity, else the static line."""
    return _brain_line(prop, a, "say_before") or f"Let's {describe(a)}."


def describe_choices(s: Session, a: Activity, m: set[str], n: int) -> str:
    kinds = [a.kind] + [k for k in ("read_listen", "practise_errors", "review_anki", "add_cards", "read_aloud",
                                    "break", "end") if k in m and k != a.kind]
    names = [DESCRIBE.get(k, k) for k in kinds[:n]]
    return ", ".join(names[:-1]) + (" or " if len(names) > 1 else "") + names[-1]


async def negotiate(s: Session, prop, menu: set[str], epoch: tuple) -> Run | _Reobserve:
    props = [p for p in ([getattr(prop, "activity", None), getattr(prop, "alternative", None)] if prop else []) if p]
    b = s.boundary
    talk = s.talk
    st = s.settings
    while True:
        if b.wanted:
            a = await first_constructible(s, [learner_spec(s, b.wanted)], menu)
            s.checkpoint()
            if s.epoch() != epoch:
                return REOBSERVE
            if a is not None:
                return Run(replace(a, decided_by="learner", override="learner_choice"))
            await talk.say(f"I can't {DESCRIBE.get(b.wanted, b.wanted)} right now.")
            b.excluded.add(b.wanted)
            b.wanted = None
        if b.reask:
            a = b.current
            b.reask = False
        else:
            if b.offers >= st["negotiation.max_offers"]:
                return wait_or_end(s)
            m = menu - b.excluded
            chain = default_chain(s, m - {"end"})
            listed = {p.kind for p in props} | {c.kind for c in chain}
            cands = [p for p in props if p.kind in m] + chain + other_allowed(s, m, listed - {"end"})
            a = await first_constructible(s, cands, m)
            s.checkpoint()
            if s.epoch() != epoch:
                return REOBSERVE
            s.latch.drain_skips()  # a skip before an offer is heard excludes nothing
            if a is None:
                return wait_or_end(s)
            b.current = a
            b.offers += 1
        m = menu - b.excluded
        autonomy = s.autonomy
        if autonomy >= st["bands.announce"]:
            await talk.say(announcement(prop, a), epoch=epoch)  # D12: never spoken under a newer epoch
            s.checkpoint()
            if s.take_skip():
                _exclude(s, a.kind)
                continue
            return REOBSERVE if s.epoch() != epoch else Run(a)
        owner = ("offer", s.latch.epoch.turn_id, b.offers)  # D21: the offer's lines and its answer, one prompt
        reason = rationale_line(prop, a)
        if autonomy >= st["bands.argue"]:
            await talk.ask(owner, reason, epoch=epoch)
        elif autonomy >= st["bands.ask"]:
            await talk.ask(owner, reason, epoch=epoch)
            await talk.ask(owner, f"Shall we {describe(a)}? Or something else?")
        else:
            await talk.ask(owner, f"Would you like to {describe_choices(s, a, m, st['negotiation.choices'])}?")
        u = await talk.listen(float(st["negotiation.ask_s"]), owner, accepts_page=True)
        if u is not None and s.on_page is not None and (pc := controls.of(u)) is not None \
                and pc.kind == "page":
            s.on_page(u)  # a page turn during an offer: the boundary re-observes for the new page (D21)
            return REOBSERVE
        c = parse_choice(u)
        s.checkpoint()
        if s.epoch() != epoch:
            return REOBSERVE
        if s.take_skip() or c in ("skip", "no"):
            _exclude(s, a.kind)
            continue
        if c == "yes":
            return Run(a)
        if c.startswith("named:"):
            named = c.removeprefix("named:")
            if named == "end":
                return Run(Activity("end", {}, "learner", override="learner_choice"))
            if named in menu:
                b.excluded.discard(named)  # the learner's choice overrides a refusal
                b.wanted = named
            else:
                await talk.say(f"We can't {DESCRIBE.get(named, named)} right now.")
            continue
        if autonomy >= st["bands.argue"]:
            return Run(a)  # none / unparsed: no objection
        b.silences += 1
        if b.silences <= st["negotiation.silence_reasks"]:
            b.reask = True
            continue
        return wait_or_end(s)
