"""Pseudonymisation by lists (M5 design D10) on a real database: scripts, possessives, hyphens, schools, stored and
one-off surrogates, reallocation, forgotten learners, and replies mapped back only where the request sent them."""

from __future__ import annotations

import pytest

from leafi.core import learner_store
from leafi.core.storage import Store
from leafi.privacy import pseudonym
from leafi.privacy import settings as privacy
from leafi.privacy.pseudonym import Mapping

KEY = b"k" * 32


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "leafi.db") as s:
        yield s


def _p(store):
    return pseudonym.build(store.conn, KEY)


def _apply(p, text):
    m = Mapping()
    return p.apply(text, m), m


def test_names_aliases_schools_and_other_terms(store):
    rocco = learner_store.create(store, "Rocco")
    store.execute("UPDATE learners SET alias='Ro' WHERE id=?", (rocco,))
    privacy.set_school(store, rocco, "James McKinney Elementary School")
    store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('Maple Street', 'other', 't')")
    p = _p(store)
    sur = p.names[f"learner:{rocco}"]
    out, m = _apply(p, "Rocco (Ro) goes to James  McKinney elementary school on Maple Street.")
    assert out == f"{sur} ({sur}) goes to the school on [place]."
    assert m.back == {sur: "Rocco"}
    assert "Rocco" not in out and "McKinney" not in out


def test_script_aware_boundaries_possessives_and_hyphens(store):
    learner_store.create(store, "Rocco")
    learner_store.create(store, "Ann")
    learner_store.create(store, "小明")
    p = _p(store)
    r, a, x = (p.names[f"learner:{i}"] for i in (1, 2, 3))
    assert _apply(p, "我叫Rocco今天读书")[0] == f"我叫{r}今天读书"
    assert _apply(p, "Roccoli and Annie and Anne")[0] == "Roccoli and Annie and Anne"
    assert _apply(p, "Rocco's and Rocco’s book; Ann-Marie; ann")[0] == f"{r}'s and {r}’s book; {a}-Marie; {a}"
    assert _apply(p, "今天小明和小明的妈妈")[0] == f"今天{x}和{x}的妈妈"
    assert _apply(p, "ROCCO")[0] == r


def test_nfc_normalisation(store):
    learner_store.create(store, "Zoë")
    p = _p(store)
    decomposed = "Zoë reads"
    assert _apply(p, decomposed)[0] == f"{p.names['learner:1']} reads"


def test_surrogates_are_stored_stable_unique_and_not_words(store):
    for n in ("Rocco", "Mia", "Leo", "Ann", "Ben"):
        learner_store.create(store, n)
    first = _p(store).names
    assert len(set(first.values())) == 5
    assert _p(store).names == first  # stored, not recomputed
    rows = store.all("SELECT entity, surrogate FROM pseudonyms")
    assert {r["entity"]: r["surrogate"] for r in rows} == first
    assert not {"River", "Sky", "Robin", "Rose"} & set(pseudonym.surrogate_pool())


def test_a_surrogate_that_becomes_a_household_name_is_reallocated(store):
    learner_store.create(store, "Rocco")
    old = _p(store).names["learner:1"]
    learner_store.create(store, old)  # someone really called that enrols
    new = _p(store).names["learner:1"]
    assert new != old


def test_a_surrogate_already_in_the_payload_gets_a_one_off_alternate(store):
    learner_store.create(store, "Rocco")
    p = _p(store)
    stored = p.names["learner:1"]
    out, m = _apply(p, f"Rocco met {stored}. Rocco waved.")
    alt = out.split()[0]
    assert alt != stored and out == f"{alt} met {stored}. {alt} waved."
    assert m.back == {alt: "Rocco"}  # the page's own word is not mapped back
    assert _p(store).names["learner:1"] == stored  # the stored surrogate is unchanged


def test_reverse_only_what_was_sent_case_sensitive_whole_word(store):
    learner_store.create(store, "Rocco")
    p = _p(store)
    sur = p.names["learner:1"]
    out, m = _apply(p, "Rocco read to the school.")
    reply = f"Well done, {sur}! {sur.lower()} and {sur}ish stay; the school and [place] stay."
    assert m.reverse(reply) == f"Well done, Rocco! {sur.lower()} and {sur}ish stay; the school and [place] stay."
    assert Mapping().reverse(reply) == reply


def test_a_forgotten_learners_terms_share_one_surrogate(store):
    store.execute("INSERT INTO household_terms(term, kind, former_learner_id, created_at) VALUES('Mia', 'name', 7, 't')")
    store.execute("INSERT INTO household_terms(term, kind, former_learner_id, created_at) VALUES('Mimi', 'name', 7, 't')")
    p = _p(store)
    out, _ = _apply(p, "Mia, also Mimi")
    sur = p.names["former:7"]
    assert out == f"{sur}, also {sur}"


def test_a_retired_redact_terms_is_protected_once_egress_imports_it(settings, monkeypatch):
    """M5d: the key is gone from Settings; egress imports a leftover value into `household_terms` at start."""
    from leafi.privacy import egress, secret

    monkeypatch.setenv("REDACT_TERMS", "Grandma Rose, Maple Street")
    secret._forget_cache()
    e = egress.Egress(settings, env_file=settings.data_dir / "no.env")
    try:
        with Store(settings.db_path) as store:
            p = _p(store)
            out, m = _apply(p, "Grandma Rose came to Maple Street")
            assert "Rose" not in out and "Maple" not in out and len(m.back) == 2
            assert e.import_legacy_terms(settings.data_dir / "no.env") == 0  # idempotent
    finally:
        e.close()
