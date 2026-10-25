"""ADR-0017 §3.3: the default policy is a setting; its chain falls through to the next constructible step."""

from __future__ import annotations

import pytest

from leafi.study.harness import policy
from leafi.study.harness import settings as hs
from leafi.study.harness.construct import first_constructible
from leafi.study.harness.menu import allowed
from leafi.study.harness.state import Facts
from tests.harness_helpers import make_session

ALL = Facts(first_boundary=True, anki_reachable=True, anki_due=2, has_book=True, unread_current=True,
            recall_due=(4,), open_candidates=(1,), cardable_items=(7,))


def test_built_in_order(tmp_path):
    s = make_session(tmp_path, facts=ALL, cycle=True)
    kinds = [sp.kind for sp in policy.default_chain(s, allowed(s))]
    # `teach_items` is Brain-owned and the session has no Brain, so the menu does not offer it (S6, D14)
    assert kinds == ["review_anki", "recall_items", "practise_errors", "add_cards", "read_listen", "end"]
    assert policy.policy_version(policy.BUILT_IN) == policy.policy_version(list(policy.BUILT_IN))


def test_a_reordered_policy_is_followed_and_has_its_own_version(tmp_path):
    order = [{"kind": "read_listen", "when": "unread"}, {"kind": "practise_errors", "when": "has_candidates"},
             {"kind": "end", "when": "always"}]
    s = make_session(tmp_path, facts=ALL, cycle=True, values={"policy.default_order": order})
    assert [sp.kind for sp in policy.default_chain(s, allowed(s))] == ["read_listen", "practise_errors", "end"]
    assert policy.policy_version(order) != policy.policy_version(policy.BUILT_IN)


async def test_a_step_that_cannot_be_constructed_falls_through_to_the_next_not_to_end(tmp_path):
    # read_listen is owned by the Brain here and there is no Brain: the chain goes on to read_aloud, not end
    order = [{"kind": "read_listen", "when": "unread"}, {"kind": "read_aloud", "when": "unread"},
             {"kind": "end", "when": "always"}]
    s = make_session(tmp_path, facts=ALL, values={"policy.default_order": order,
                                                  "policy.content.read_listen": "brain"})
    a = await first_constructible(s, policy.default_chain(s, allowed(s)), allowed(s))
    assert a is not None and a.kind == "read_aloud"


def test_an_invalid_order_is_refused_at_save_and_the_built_in_is_used(tmp_path):
    s = make_session(tmp_path)
    for bad in ([], [{"kind": "dance", "when": "always"}], [{"kind": "end", "when": "sometimes"}],
                [{"kind": "end", "when": "always"}, {"kind": "end", "when": "always"}]):
        with pytest.raises(hs.InvalidSetting):
            hs.save(s.store, s.learner_id, {"policy.default_order": bad})
    s2 = make_session(tmp_path / "b", values={"policy.default_order": [{"kind": "dance"}]})  # stored by hand
    assert policy.order_of(s2) == policy.BUILT_IN
