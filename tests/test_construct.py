"""ADR-0017 §3.3 construction, code content-owner cases (the Brain cases arrive with M7)."""

from __future__ import annotations

from leafi.study.harness.construct import construct
from leafi.study.harness.state import Activity, Facts, Rejected, Spec
from tests.harness_helpers import make_session

F = Facts(has_book=True, unread_current=True, open_candidates=(11, 12, 13), cardable_items=(7, 8), anki_due=30,
          anki_reachable=True)


def test_a_brain_specs_content_fields_are_discarded_when_the_owner_is_code(tmp_path):
    s = make_session(tmp_path, facts=F, cycle=True)
    a = construct(s, Spec("add_cards", {"item_ids": [7]}, content={"front": "x", "back": "y"}, source="brain"))
    assert isinstance(a, Activity) and a.content is None and a.content_owner == "code" and a.decided_by == "brain"


def test_a_brain_owned_kind_without_a_brain_is_not_available(tmp_path):
    s = make_session(tmp_path, facts=F, values={"policy.content.read_aloud": "brain"})
    assert construct(s, Spec("read_aloud", {"page": "current"})) == Rejected("not available now")


def test_selection_ids_belong_to_the_current_state_and_the_ledger(tmp_path):
    s = make_session(tmp_path, facts=F, cycle=True, values={"practice.max_errors": 2, "cards.max": 1})
    a = construct(s, Spec("practise_errors", {"candidate_ids": [99, 13, 11, 12]}))
    assert a.params == {"candidate_ids": [13, 11]}  # unknown ids dropped, trimmed to the cycle's budget
    assert construct(s, Spec("practise_errors", {"candidate_ids": [99]})) == Rejected("no candidates to practise")
    assert construct(s, Spec("add_cards", {"item_ids": [7, 8]})).params == {"item_ids": [7]}
    assert construct(s, Spec("review_anki", {"max_cards": 50})).params == {"max_cards": 20}
    assert isinstance(construct(s, Spec("break", {"seconds": 600})), Rejected)


def test_a_new_page_carries_no_sentence_ids_and_current_needs_unread_text(tmp_path):
    s = make_session(tmp_path, facts=Facts(has_book=True, can_acquire_next_page=True))
    assert isinstance(construct(s, Spec("read_listen", {"page": "current"})), Rejected)
    assert isinstance(construct(s, Spec("read_listen", {"page": "next", "range": {"from": 1, "to": 2}})), Rejected)
    assert construct(s, Spec("read_listen", {"page": "next"})).params == {"page": "next", "range": "rest"}


def test_a_kind_outside_the_menu_and_a_url_are_rejected(tmp_path):
    s = make_session(tmp_path, facts=F)
    assert construct(s, Spec("practise_errors", {"candidate_ids": [11]})) == Rejected("not allowed now")  # no cycle
    s2 = make_session(tmp_path / "b", facts=F, values={"policy.content.add_cards": "brain"}, cycle=True)
    s2.generate = object()
    assert construct(s2, Spec("add_cards", {"item_ids": [7]}, content={"back": "see https://x.example"})) == \
        Rejected("no URLs")
