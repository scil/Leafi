"""ADR-0017 §3.3 construction: the `code` content owner, and the `brain` owner's one `generate` call per
(boundary, kind, selection), cached with its epoch (M7 design D14)."""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from leafi.core.ports import Section
from leafi.core.provenance import Leaf, Provenance
from leafi.services.brain.mock import MockModel
from leafi.study.brain import call as bc
from leafi.study.brain import generate
from leafi.study.harness.construct import construct, first_constructible
from leafi.study.harness.state import Activity, Facts, Rejected, Spec
from tests.harness_helpers import make_session

F = Facts(has_book=True, unread_current=True, open_candidates=(11, 12, 13), cardable_items=(7, 8), anki_due=30,
          anki_reachable=True)


async def test_a_brain_specs_content_fields_are_discarded_when_the_owner_is_code(tmp_path):
    s = make_session(tmp_path, facts=F, cycle=True)
    a = await construct(s, Spec("add_cards", {"item_ids": [7]}, content={"front": "x", "back": "y"}, source="brain"))
    assert isinstance(a, Activity) and a.content is None and a.content_owner == "code" and a.decided_by == "brain"


async def test_a_brain_owned_kind_without_a_brain_is_not_available(tmp_path):
    s = make_session(tmp_path, facts=F, values={"policy.content.read_aloud": "brain"})
    assert await construct(s, Spec("read_aloud", {"page": "current"})) == Rejected("not available now")


async def test_selection_ids_belong_to_the_current_state_and_the_ledger(tmp_path):
    s = make_session(tmp_path, facts=F, cycle=True, values={"practice.max_errors": 2, "cards.max": 1})
    a = await construct(s, Spec("practise_errors", {"candidate_ids": [99, 13, 11, 12]}))
    assert a.params == {"candidate_ids": [13, 11]}  # unknown ids dropped, trimmed to the cycle's budget
    assert await construct(s, Spec("practise_errors", {"candidate_ids": [99]})) == \
        Rejected("no candidates to practise")
    assert (await construct(s, Spec("add_cards", {"item_ids": [7, 8]}))).params == {"item_ids": [7]}
    assert (await construct(s, Spec("review_anki", {"max_cards": 50}))).params == {"max_cards": 20}
    assert isinstance(await construct(s, Spec("break", {"seconds": 600})), Rejected)


async def test_a_new_page_carries_no_sentence_ids_and_current_needs_unread_text(tmp_path):
    s = make_session(tmp_path, facts=Facts(has_book=True, can_acquire_next_page=True))
    assert isinstance(await construct(s, Spec("read_listen", {"page": "current"})), Rejected)
    assert isinstance(await construct(s, Spec("read_listen", {"page": "next", "range": {"from": 1, "to": 2}})),
                      Rejected)
    assert (await construct(s, Spec("read_listen", {"page": "next"}))).params == {"page": "next", "range": "rest"}


async def test_a_kind_outside_the_menu_is_rejected(tmp_path):
    s = make_session(tmp_path, facts=F)
    assert await construct(s, Spec("practise_errors", {"candidate_ids": [11]})) == Rejected("not allowed now")


# ---------------------------------------------------------------- the `brain` owner (D14)


class _Card(BaseModel):
    back: str


def _check(s, sel, value):
    return Rejected("empty") if not value.back else {"back": value.back}


@pytest.fixture
def card_generator(monkeypatch):
    gen = generate.Generator(_Card, lambda s, sel: (Section("page", (Leaf("The fox ran home.", Provenance("page")),)),),
                             _check)
    monkeypatch.setitem(generate.GENERATORS, "add_cards", gen)
    return gen


def _brain_session(tmp_path, reply):
    s = make_session(tmp_path, facts=F, cycle=True, values={"policy.content.add_cards": "brain"})
    model = MockModel({"generate": reply})
    s.brain = bc.Brain({"fast": [], "standard": [(model, "mock-gen")], "deep": []})
    return s, model


MENU = {"add_cards", "read_listen", "end"}


async def test_one_generate_call_per_boundary_kind_and_selection(tmp_path, card_generator):
    s, model = _brain_session(tmp_path, {"back": "a small wild dog"})
    a = await construct(s, Spec("add_cards", {"item_ids": [7]}, content={"back": "ignored"}, source="brain"), MENU)
    assert isinstance(a, Activity) and a.content == {"back": "a small wild dog"} and a.content_owner == "brain"
    assert a.content_provenance.cls == "page"  # D2: of_output over what was sent
    again = await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU)  # a re-offer, a silence re-ask
    assert again.content == a.content and len(model.requests) == 1
    other = await construct(s, Spec("add_cards", {"item_ids": [8]}), MENU)  # another selection: its own call
    assert isinstance(other, Activity) and len(model.requests) == 2
    assert model.requests[0].purpose == "generate"


async def test_a_reoffer_reuses_cached_content_after_the_allowance_is_spent(tmp_path, card_generator):
    s, model = _brain_session(tmp_path, {"back": "a small wild dog"})
    first = await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU)
    s.ledger.brain_spent = 1000  # the session's Brain allowance is gone
    s.boundary.moment = time.monotonic() - 1  # and so is the boundary's moment
    again = await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU)
    assert again.content == first.content and len(model.requests) == 1


async def test_a_changed_epoch_discards_the_cached_content(tmp_path, card_generator):
    s, model = _brain_session(tmp_path, {"back": "a small wild dog"})
    await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU)
    s.latch.epoch.bump()  # a Reobserve
    await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU)
    assert len(model.requests) == 2


async def test_a_failed_generation_is_not_asked_again_at_the_boundary(tmp_path, card_generator):
    s, model = _brain_session(tmp_path, {"back": ""})
    assert await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU) == Rejected("empty")
    assert await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU) == Rejected("empty")
    assert len(model.requests) == 1


async def test_a_spent_moment_skips_brain_owned_candidates_without_a_call(tmp_path, card_generator):
    s, model = _brain_session(tmp_path, {"back": "a small wild dog"})
    s.boundary.moment = time.monotonic() + 0.5  # less than any tier's minimum
    chain = [Spec("add_cards", {"item_ids": [7]}), Spec("read_listen", {"page": "current"})]
    a = await first_constructible(s, chain, MENU)
    assert a.kind == "read_listen" and a.content_owner == "code" and model.requests == []


async def test_generated_content_holding_a_url_is_rejected(tmp_path, card_generator):
    s, _ = _brain_session(tmp_path, {"back": "see https://x.example"})
    assert await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU) == Rejected("no URLs")


async def test_a_reply_outside_the_kinds_schema_escalates_and_then_falls_through(tmp_path, card_generator):
    s, model = _brain_session(tmp_path, {"front": "x"})  # no `back`: invalid on every tier
    assert await construct(s, Spec("add_cards", {"item_ids": [7]}), MENU) == Rejected("not available now")
    assert s.store.one("SELECT outcome FROM brain_calls WHERE purpose='generate'")["outcome"] == "invalid"
