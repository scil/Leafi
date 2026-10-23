"""The configurable default policy (ADR-0017 §3.3): an ordered list of steps `{kind, when}`, a fixed `when`
vocabulary, a `policy_version` hash recorded on every boundary; an invalid order is refused at save and the
built-in default is used."""

from __future__ import annotations

import hashlib
import json

from leafi.study.harness.state import Facts, Session, Spec

WHEN = ("first_boundary", "has_recall_due", "has_candidates", "has_new_items", "has_cardable", "unread", "always")
POLICY_KINDS = ("review_anki", "read_listen", "read_aloud", "practise_errors", "teach_items", "recall_items",
                "quiz", "learner_questions", "add_cards", "break", "end")
BUILT_IN: list[dict] = [
    {"kind": "review_anki", "when": "first_boundary"},
    {"kind": "recall_items", "when": "has_recall_due"},
    {"kind": "practise_errors", "when": "has_candidates"},
    {"kind": "teach_items", "when": "has_new_items"},
    {"kind": "add_cards", "when": "has_cardable"},
    {"kind": "read_listen", "when": "unread"},
    {"kind": "end", "when": "always"},
]


def invalid_order(order) -> str | None:
    if not isinstance(order, list) or not order:
        return "must be a non-empty list of steps"
    seen = set()
    for i, step in enumerate(order, 1):
        if not isinstance(step, dict) or set(step) != {"kind", "when"}:
            return f"step {i} must be {{kind, when}}"
        if step["kind"] not in POLICY_KINDS:
            return f"step {i}: unknown kind {step['kind']!r}"
        if step["when"] not in WHEN:
            return f"step {i}: unknown when {step['when']!r}"
        key = (step["kind"], step["when"])
        if key in seen:
            return f"step {i} repeats {step['kind']} / {step['when']}"
        seen.add(key)
    return None


def order_of(s: Session) -> list[dict]:
    order = s.settings["policy.default_order"]
    return order if invalid_order(order) is None else BUILT_IN


def policy_version(order: list[dict]) -> str:
    return hashlib.sha256(json.dumps(order, sort_keys=True).encode()).hexdigest()[:12]


def holds(when: str, f: Facts) -> bool:
    return {"first_boundary": f.first_boundary, "has_recall_due": bool(f.recall_due),
            "has_candidates": bool(f.open_candidates), "has_new_items": bool(f.new_item_candidates),
            "has_cardable": bool(f.cardable_items), "unread": f.unread_current or f.can_acquire_next_page,
            "always": True}[when]


def default_selection(kind: str, f: Facts) -> dict:
    """Selection fields of a default step (§3.3 table)."""
    if kind == "read_listen":
        return {"page": "current", "range": "rest"} if f.unread_current else {"page": "next", "range": "rest"}
    if kind == "read_aloud":
        return {"page": "current", "range": "rest"}
    if kind == "practise_errors":
        return {"candidate_ids": list(f.open_candidates)}  # trimmed to the ledger by construction
    if kind == "review_anki":
        return {"max_cards": min(f.anki_due, 20)}
    if kind == "recall_items":
        return {"item_ids": list(f.recall_due)}
    if kind == "add_cards":
        return {"item_ids": list(f.cardable_items)}
    if kind == "teach_items":
        return {"item_ids": list(f.new_item_candidates)}
    if kind == "break":
        return {"seconds": 60}
    return {}


def default_chain(s: Session, menu: set[str]) -> list[Spec]:
    """Every step, in order, whose kind is in `menu` and whose `when` holds."""
    f = s.facts()
    return [Spec(step["kind"], default_selection(step["kind"], f), source="default")
            for step in order_of(s) if step["kind"] in menu and holds(step["when"], f)]
