"""The local WordInfo backend (plan M0.2, M0.3): espeak-ng phones with homographs, lemminflect lemmas with
the overrides, word lists or lemminflect's dictionary for `is_word`."""

from __future__ import annotations

import pytest

from leafi.services.wordinfo import LocalWordInfo


@pytest.fixture(scope="module")
def info(tmp_path_factory):
    return LocalWordInfo(tmp_path_factory.mktemp("models"), lexicon=["kipper"])


def test_homophones_and_homographs_share_phones(info):
    if info.versions["phones"] == "none":
        pytest.skip("espeak-ng phonemizer unavailable")
    info.prepare(["through", "threw", "read", "red"])
    assert info.phones("through") & info.phones("threw")
    assert info.phones("read") & info.phones("red")


def test_lemmas_link_inflections_and_not_look_alikes(info):
    assert info.lemmas("walked") & info.lemmas("walk")
    assert info.lemmas("had") & info.lemmas("has")
    assert not info.lemmas("card") & info.lemmas("car")
    assert "numb" not in info.lemmas("number")  # override


def test_is_word_uses_the_lexicon_then_a_dictionary(info):
    assert info.is_word("kipper") and info.is_word("house")
    assert not info.is_word("hosre")


def test_word_lists_decide_when_installed(tmp_path):
    (tmp_path / "wordlists").mkdir()
    (tmp_path / "wordlists" / "en_US.txt").write_text("house\nhorse\n", encoding="utf-8")
    info = LocalWordInfo(tmp_path)
    assert info.is_word("house") and not info.is_word("cat")
    assert info.versions["wordlists"] == "scowl-60-2026.02.25"
    (tmp_path / "wordlists" / "en_GB-ise.txt").write_text("colour\n", encoding="utf-8")
    (tmp_path / "wordlists" / "cyplex.txt").write_text("gruffalo\n", encoding="utf-8")
    info = LocalWordInfo(tmp_path)
    assert info.is_word("colour") and info.is_word("gruffalo")
    assert info.versions["wordlists"] == "scowl-60-2026.02.25,cyplex-2024-03-21-min3"


def test_cyplex_extract_keeps_word_forms_from_the_minimum_count(tmp_path):
    from leafi.services.wordinfo import build_cyplex

    header = "Word,Count,Zipf_freq,Lemma\n"
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text(header + "Gruffalo,12,3.1,gruffalo\nteh,1,1.0,teh\nmice,3,4.0,mouse\n", encoding="utf-8")
    b.write_text("﻿" + header + "mice,40,4.5,mouse\nhagrid,2,2.0,hagrid\nwalked,9,4.2,walk\n",
                 encoding="utf-8")  # main_cyplex1012.csv starts with a BOM
    out = tmp_path / "wordlists" / "cyplex.txt"
    assert build_cyplex([a, b], out) == 3
    assert out.read_text(encoding="utf-8").splitlines() == ["gruffalo", "mice", "walked"]
