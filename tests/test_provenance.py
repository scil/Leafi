"""Provenance of Brain outputs (M7 design D2): the output of a call carries every restriction of what it was given,
including the reserved parent-origin source 0, so a later cloud call checks a learner's `cloud.text` and the
household's CLOUD_PARENT_TEXT together. Pure rules plus the fence on real SQLite."""

from __future__ import annotations

import pytest

from leafi.core import learner_store
from leafi.core.provenance import PARENT_SOURCE, SYSTEM, Provenance, of_output
from leafi.core.storage import Store, now_iso


def test_an_output_of_page_text_alone_is_page():
    assert of_output([Provenance("page"), SYSTEM]) == Provenance("page")
    assert of_output([]) == SYSTEM
    assert of_output([SYSTEM]) == SYSTEM


def test_an_output_quoting_a_learner_derives_from_them_never_is_them():
    out = of_output([Provenance("learner", (3,)), Provenance("page")])
    assert out == Provenance("derived_from_learner", (3,))
    assert of_output([Provenance("derived_from_learner", (3,)), Provenance("learner", (5,))]) == \
        Provenance("derived_from_learner", (3, 5))


def test_parent_text_alone_stays_parent_and_mixed_with_a_learner_keeps_both_restrictions():
    assert of_output([Provenance("parent"), Provenance("page")]) == Provenance("parent")
    mixed = of_output([Provenance("parent"), Provenance("derived_from_learner", (4,))])
    assert mixed == Provenance("derived_from_learner", (PARENT_SOURCE, 4))
    assert mixed.learner_sources == (4,) and mixed.parent_origin


def test_the_fence_ignores_the_parent_source_but_still_checks_the_learner(tmp_path):
    store = Store(tmp_path / "leafi.db")
    ada = learner_store.create(store, "Ada")
    ben = learner_store.create(store, "Ben")
    cls, src = learner_store.prov("derived_from_learner", [ben, PARENT_SOURCE])
    assert learner_store.stated_sources({"x_source_learners": src}) == {ben}
    note = dict(text="likes dinosaurs", provenance_class=cls, source_learners=src, created_at=now_iso())
    learner_store.insert(store, "learner_notes", ada, **note)  # 0 names nobody: accepted
    learner_store.insert(store, "learner_notes", ada, sources=[PARENT_SOURCE], **note)
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ben,))
    with pytest.raises(learner_store.LearnerUnavailable):
        learner_store.insert(store, "learner_notes", ada, **note)
