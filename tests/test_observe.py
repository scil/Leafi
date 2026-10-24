"""The `decide` observation (ADR-0017 §4; M7 design D3, D6, D12, D15): order, provenance, substitutes, ids."""

from __future__ import annotations

from leafi.study.brain.observe import Candidate, Item, ObservationInput, observe


def _input(**kw):
    base = dict(page_read_id=3, sentences=((1, "The fox ran."), (2, "It was late.")), unread_from=2,
                difficulties=(("horse", 2.0),), candidates=(Candidate(12, "horse", "house", "substitution", 7),),
                new_items=(Item(5, "late", "word"),), menu=("practise_errors", "read_listen", "end"),
                default_chain=("practise_errors", "read_listen", "end"),
                last_activity={"id": 40, "kind": "read_listen", "status": "completed", "sentences": 1},
                session={"elapsed_min": 4, "autonomy": 5}, turn=9)
    return ObservationInput(**{**base, **kw})


def test_sections_come_in_the_one_rendering_order():
    names = [s.name for s in observe(_input()).sections]
    assert names == ["page", "memory", "cycle", "menu", "last_activity", "session", "turn"]
    assert [s.name for s in observe(_input(difficulties=(), last_activity=None)).sections] == \
        ["page", "cycle", "menu", "session", "turn"]


def test_a_learners_words_carry_their_provenance_and_a_substitute():
    cycle = next(s for s in observe(_input()).sections if s.name == "cycle")
    heard = [leaf for leaf in cycle.leaves if "heard" in leaf.value]
    (h,) = heard
    assert h.prov.cls == "learner" and h.prov.sources == (7,) and "house" in h.value
    assert h.substitute is not None and "house" not in h.substitute
    assert all(leaf.prov.cls == "page" for leaf in cycle.leaves if leaf is not h)


def test_ids_are_rendered_and_mapped_back_and_the_turn_is_opaque():
    o = observe(_input())
    assert o.ids["m12"] == ("candidate", 12) and o.ids["s3.2"] == ("sentence", 2) and o.ids["i5"] == ("item", 5)
    assert o.ids["a40"] == ("activity", 40) and o.turn == "t9"
    assert all("session_id" not in leaf.value for s in o.sections for leaf in s.leaves)
