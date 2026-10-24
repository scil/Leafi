"""Construction (ADR-0017 §3.3): validate a spec against the current state and build the activity.

1. `kind ∈ allowed(s)` (the harness-internal `end` and `wait` are exempt, §2.1); 2. selection fields from the spec,
content fields only from the content owner (`code`: built from stored data at run time, Brain content discarded;
`brain`: one `generate` call, M7); 3. ids belong to the current state; 4. counts within the ledger's remaining
budgets, lengths, no URLs.
"""

from __future__ import annotations

import re

from leafi.study.harness.menu import allowed
from leafi.study.harness.state import Activity, Rejected, Session, Spec

URL = re.compile(r"https?://|www\.", re.IGNORECASE)
INTERNAL = ("end", "wait")


def _has_url(value) -> bool:
    if isinstance(value, str):
        return bool(URL.search(value))
    if isinstance(value, dict):
        return any(_has_url(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_url(v) for v in value)
    return False


def _selection(s: Session, spec: Spec) -> dict | Rejected:
    f = s.facts()
    p = dict(spec.params)
    k = spec.kind
    if k == "read_listen" or k == "read_aloud":
        page = p.get("page", "current")
        if page not in ("current", "next", "familiar"):
            return Rejected("unknown page")
        rng = p.get("range", "rest")
        if page == "current":
            if not f.unread_current:
                return Rejected("nothing left to read on this page")
            if rng != "rest" and not (isinstance(rng, dict) and 0 < rng.get("from", 0) <= rng.get("to", 0)):
                return Rejected("range must be rest or {from, to}")
        else:
            if page == "next" and not f.can_acquire_next_page:
                return Rejected("no next page")
            if page == "familiar" and not f.familiar_pages:
                return Rejected("no familiar page")
            if rng != "rest":
                return Rejected("a new page carries no sentence ids")
        return {"page": page, "range": rng}
    if k == "practise_errors":
        ids = [i for i in p.get("candidate_ids", []) if i in f.open_candidates]
        if s.cycle_id is None:
            return Rejected("no open cycle")
        ids = ids[: s.ledger.cycle_errors_left(s.cycle_id)]
        return {"candidate_ids": ids} if ids else Rejected("no candidates to practise")
    if k == "review_anki":
        n = min(int(p.get("max_cards", f.anki_due)), f.anki_due, 20)
        return {"max_cards": n} if n > 0 else Rejected("no cards due")
    if k == "recall_items":
        ids = [i for i in p.get("item_ids", []) if i in f.recall_due]
        return {"item_ids": ids} if ids else Rejected("nothing to recall")
    if k == "add_cards":
        ids = [i for i in p.get("item_ids", []) if i in f.cardable_items][: s.ledger.cards_left()]
        return {"item_ids": ids} if ids else Rejected("no cards to add")
    if k == "teach_items":
        ids = [i for i in p.get("item_ids", []) if i in f.new_item_candidates]
        if s.cycle_id is not None:
            ids = ids[: s.ledger.cycle_new_left(s.cycle_id)]
        return {"item_ids": ids} if ids else Rejected("no new items")
    if k == "break":
        sec = int(p.get("seconds", 60))
        return {"seconds": sec} if 0 < sec <= 120 else Rejected("a break is 1-120 s")
    if k == "learner_questions":
        return {"max_turns": min(int(p.get("max_turns", 5)), 5)}
    if k == "quiz":
        if s.cycle_id is None or s.ledger.cycle_quiz_left(s.cycle_id) <= 0:
            return Rejected("no questions left in this cycle")
        return {"evidence_sentence_ids": [r for r in p.get("evidence_sentence_ids", []) if isinstance(r, str)]}
    return p


async def construct(s: Session, spec: Spec, menu: set[str] | None = None) -> Activity | Rejected:
    if spec.kind in INTERNAL:
        return Activity(spec.kind, dict(spec.params), spec.source)
    if spec.kind not in (menu if menu is not None else allowed(s)):
        return Rejected("not allowed now")
    sel = _selection(s, spec)
    if isinstance(sel, Rejected):
        return sel
    owner = s.settings[f"policy.content.{spec.kind}"]
    if owner != "brain":  # `code`: built from stored data at run time; a spec's content fields are discarded
        return Rejected("no URLs") if _has_url(sel) else Activity(spec.kind, sel, spec.source, content_owner=owner)
    from leafi.study.brain import generate  # lazy: the brain package imports the harness state

    # M7 D14: only the generated, checked content is used — never content a spec carries
    made = await generate.content(s, spec.kind, sel)
    if isinstance(made, Rejected):
        return made
    if _has_url(sel) or _has_url(made.value):
        return Rejected("no URLs")
    return Activity(spec.kind, sel, spec.source, content=made.value, content_owner=owner,
                    content_provenance=made.provenance, degraded=made.degraded)


async def first_constructible(s: Session, specs: list[Spec], menu: set[str]) -> Activity | None:
    for spec in specs:
        a = await construct(s, spec, menu)
        if isinstance(a, Activity):
            return a
    return None
