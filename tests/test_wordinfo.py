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
    assert info.versions["wordlists"] == "en_US.txt"
