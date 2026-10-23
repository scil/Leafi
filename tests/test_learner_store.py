"""Every learner-scoped writer of ADR-0018 §7.1 under two learners: rows land with their owner, lookups never
cross learners, and the fence refuses a learner being forgotten. Real SQLite, never mocked."""

from __future__ import annotations

import pytest

from leafi.core import learner_store
from leafi.core.storage import Store
from leafi.study import anki, corrections, knowledge, records
from tests import seed
from tests.fakes.anki import FakeAnki

TEXT = "The wind blew through the trees."


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


@pytest.fixture
def two(store):
    return seed.learner(store, "Ada"), seed.learner(store, "Ben")


def _confirmed_miscue(store, learner, book, page, rev, word):
    s = seed.session(store, book, learner_id=learner)
    read = seed.page_read(store, s, page, rev)
    seed.miscue(store, read, rev, TEXT, word, status="confirmed")
    return s


def test_items_and_cards_are_per_learner(store, two):
    ada, ben = two
    a = knowledge.upsert_item(store, ada, "word", "blew")
    b = knowledge.upsert_item(store, ben, "word", "blew")
    assert a != b and knowledge.upsert_item(store, ada, "word", "blew") == a
    seed.card(store, a)
    seed.card(store, b)
    owners = {r["knowledge_item_id"]: r["learner_id"] for r in store.all("SELECT * FROM anki_outbox")}
    assert owners == {a: ada, b: ben}
    e = knowledge.add_encounter(store, b, session_id=None, trigger="explain", explanation_en="moved air")
    row = store.one("SELECT * FROM encounters WHERE id=?", (e,))
    assert row["learner_id"] == ben and row["explanation_source_learners"] == f"[{ben}]"
    assert row["context_provenance_class"] == "page"


def test_difficulties_and_practice_order_never_cross_learners(store, two):
    ada, ben = two
    book, page, rev = seed.book_page(store, TEXT)
    _confirmed_miscue(store, ada, book, page, rev, "trees")
    _confirmed_miscue(store, ben, book, page, rev, "wind")
    assert {(r["learner_id"], r["miscue_key"]) for r in store.all("SELECT * FROM difficulties")} == {
        (ada, "trees"), (ben, "wind")}
    cands = [(1, "wind"), (5, "trees")]
    assert knowledge.practice_order(store, ada, cands) == [(5, "trees"), (1, "wind")]
    assert knowledge.practice_order(store, ben, cands) == [(1, "wind"), (5, "trees")]
    knowledge.recompute_difficulties(store, ada)  # one learner's recompute leaves the other's rows alone
    assert store.one("SELECT COUNT(*) AS n FROM difficulties WHERE learner_id=?", (ben,))["n"] == 1


def test_a_shared_page_correction_recomputes_every_learner(store, two):
    ada, ben = two
    book, page, rev = seed.book_page(store, TEXT)
    _confirmed_miscue(store, ben, book, page, rev, "trees")
    span = corrections.locate(TEXT, "trees", near=0)
    res = corrections.apply_correction(store, page_id=page, revision_id=rev, char_start=span[0],
                                       char_end=span[1], new_text="tree", source="voice", learner_id=ada)
    assert res.invalidated and store.all("SELECT * FROM difficulties") == []
    assert store.one("SELECT source_learner_id FROM corrections")[0] == ada
    with pytest.raises(ValueError, match="needs the learner"):
        corrections.record_unlocated(store, revision_id=res.revision_id, old_text="a", new_text="b", source="text",
                                     learner_id=None)
    corrections.record_unlocated(store, revision_id=res.revision_id, old_text="a", new_text="b", source="parent",
                                 learner_id=None)


async def test_review_answers_and_decks_are_per_learner(store, two):
    ada, ben = two
    fake = FakeAnki()
    client = anki.AnkiClient(transport=fake.transport())
    seed.card(store, knowledge.upsert_item(store, ada, "word", "blew"))
    seed.card(store, knowledge.upsert_item(store, ben, "word", "wind"))
    await anki.sync_outbox(store, client)
    assert sorted(n["deck"] for n in fake.notes.values()) == ["Leafi Ada #1", "Leafi Ben #2"]
    ben_note = next(nid for nid, n in fake.notes.items() if n["deck"] == "Leafi Ben #2")
    fake.add_due_card("", note_id=ben_note)
    (card,) = await anki.due_cards(store, client, ada)  # the fake ignores the deck: the item lookup must not
    assert card.knowledge_item_id is None
    assert await anki.answer(store, client, ada, card, 2) == "acked"
    assert store.one("SELECT learner_id, ease FROM review_answers")[:] == (ada, 2)


def test_resume_and_stale_close_are_per_learner(store, two):
    from leafi.core.storage import dumps
    from leafi.study.alignment import ReadingState, align

    ada, ben = two
    book, page, rev = seed.book_page(store, TEXT, source="manual")
    s = seed.session(store, book, learner_id=ben)
    read = seed.page_read(store, s, page, rev)
    st, _, _ = align(ReadingState.from_text(TEXT), ["The", "wind"], 1)  # part-read: worth continuing
    store.execute("UPDATE page_reads SET reading_state=? WHERE id=?", (dumps(st.to_json()), read))
    assert records.close_stale_sessions(store) == [s]
    assert records.resumable_read(store, ben, book)["id"] == read
    assert records.resumable_read(store, ada, book) is None  # Ben's interrupted page is not Ada's


def test_decks_are_unique_stable_and_never_nested(store, two):
    ada, ben = two
    namesake = seed.learner(store, "Ada")
    assert anki.deck_for(store, ada) != anki.deck_for(store, namesake)
    deck = anki.deck_for(store, ben)
    store.execute("UPDATE learners SET display_name='Benjamin' WHERE id=?", (ben,))
    assert anki.deck_for(store, ben) == deck  # a rename never moves cards
    cy = seed.learner(store, "Cy")
    store.execute("UPDATE learners SET settings=? WHERE id=?", ('{"anki.deck": "Leafi Cy #4::x"}', ada))
    with pytest.raises(anki.AnkiError, match="overlap"):  # Cy's deck would contain Ada's
        anki.deck_for(store, cy)


def test_the_fence_reads_the_rows_own_provenance(store, two):
    ada, ben = two
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ada,))
    with pytest.raises(learner_store.LearnerUnavailable):  # no `sources=` given: the column still names Ada
        learner_store.insert(store, "learner_notes", ben, text="secret", provenance_class="derived_from_learner",
                             source_learners=f"[{ada}]", created_at="t")


def test_export_names_the_learner(store, two):
    ada, _ = two
    s = seed.session(store, None, learner_id=ada)
    assert records.export_session(store, s)["learner"] == ada


def test_the_fence_refuses_a_learner_being_forgotten(store, two):
    ada, ben = two
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ada,))
    with pytest.raises(learner_store.LearnerUnavailable):
        knowledge.upsert_item(store, ada, "word", "blew")
    item = knowledge.upsert_item(store, ben, "word", "blew")
    with pytest.raises(learner_store.LearnerUnavailable):  # Ben's row whose text derives from Ada
        learner_store.insert(store, "learner_notes", ben, sources=[ada], text="x", provenance_class="learner",
                             source_learners=f"[{ada}]", created_at="t")
    with pytest.raises(learner_store.LearnerUnavailable):  # and once Ada's row is gone
        learner_store.insert(store, "learner_notes", ben, sources=[999], text="x", provenance_class="learner",
                             source_learners="[999]", created_at="t")
    assert store.one("SELECT COUNT(*) AS n FROM knowledge_items")["n"] == 1 and item


def test_choose_picks_names_or_the_only_learner(store):
    with pytest.raises(learner_store.LearnerChoice, match="no learner yet"):
        learner_store.choose(store, None)
    ada, new = learner_store.choose(store, "Ada")
    assert new
    assert learner_store.choose(store, "ada") == (ada, False)
    assert learner_store.choose(store, None) == (ada, False)
    learner_store.choose(store, "Ben")
    with pytest.raises(learner_store.LearnerChoice, match="Ada .#1., Ben .#2."):
        learner_store.choose(store, None)
    with pytest.raises(learner_store.LearnerChoice, match="no learner called"):
        learner_store.choose(store, "Cy", enrol=False)
