"""The menu (ADR-0017 §3.2): which kinds may start at this boundary. Always contains `end`."""

from __future__ import annotations

from leafi.study.harness.policy import default_selection
from leafi.study.harness.state import Session, Spec

MENU_ORDER = ("review_anki", "recall_items", "practise_errors", "teach_items", "add_cards", "read_listen",
              "read_aloud", "quiz", "learner_questions", "break", "end")


def allowed(s: Session) -> set[str]:
    if s.past_soft_deadline() or s.ledger.minutes() >= s.settings.session_max_min():
        return {"end"}
    f = s.facts()
    m = {"end", "break"}
    gen = s.generate is not None and s.ledger.can_afford("standard")
    if f.anki_reachable and f.anki_due > 0 and not f.reviews_goal_met:
        m.add("review_anki")
    if f.has_book and (f.unread_current or f.can_acquire_next_page or f.familiar_pages):
        m |= {"read_listen", "read_aloud"}
    if f.recall_due:
        m.add("recall_items")
    cyc = s.cycle_id
    if cyc is not None:
        if f.open_candidates and s.ledger.cycle_errors_left(cyc) > 0:
            m.add("practise_errors")
        if f.new_item_candidates and s.ledger.cycle_new_left(cyc) > 0 and gen:
            m.add("teach_items")
        if f.read_sentences and s.ledger.cycle_quiz_left(cyc) > 0 and gen:
            m.add("quiz")
        if f.read_sentences and s.routable_answer:
            m.add("learner_questions")
        if f.cardable_items and s.ledger.cards_left() > 0:
            m.add("add_cards")
        if s.ledger.boundary_activities(cyc) >= s.settings["limits.activities_per_cycle"]:
            m &= {"read_listen", "read_aloud", "end"}  # continuations do not count
    return m


def other_allowed(s: Session, m: set[str], listed: set[str]) -> list[Spec]:
    """Specs with default params for the kinds of `m` not already listed, in MENU_ORDER, `end` last."""
    f = s.facts()
    return [Spec(k, default_selection(k, f), source="default") for k in MENU_ORDER if k in m and k not in listed]
