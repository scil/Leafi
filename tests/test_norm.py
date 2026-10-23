"""ADR-0013 v2 → norm() v2: numeral readings in canonical form; token boundaries unchanged from v1."""

from __future__ import annotations

from pathlib import Path

from leafi.core.text import TOKENIZER_VERSION, canonical_number, norm, numeral_readings, tokenize


def test_version_is_two():
    assert TOKENIZER_VERSION == "2"


def test_numerals_normalise_to_their_canonical_cardinal_or_ordinal():
    assert norm("21") == "twentyone"
    assert norm("105") == "onehundredfive"  # num2words' "and" is dropped
    assert norm("3") == "three"
    assert norm("21st") == "twentyfirst"
    assert norm("2000") == "twothousand"


def test_numeral_readings_include_the_year_reading():
    assert numeral_readings("1990") == {"onethousandninehundredninety", "nineteenninety"}
    assert numeral_readings("21st") == {"twentyfirst"}
    assert numeral_readings("cat") == frozenset()


def test_canonical_form_drops_and_commas_spaces_hyphens():
    assert canonical_number("One thousand, nine hundred and ninety") == "onethousandninehundredninety"
    assert canonical_number("twenty-one") == "twentyone"


def test_v1_normalisation_is_unchanged_for_words():
    assert norm("Don't") == "don't" and norm("dont") == "don't"
    assert norm("well-known") == "wellknown" and norm("“Hello,”") == "hello"


def test_token_boundaries_on_the_fixture_pages_are_v1s():
    """Only `norm` values changed in v2: spans and sentence ids are produced by the same regexes."""
    for p in sorted(Path("tests/fixtures/pages").glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        toks = tokenize(text)
        assert [text[t.start:t.end] for t in toks] == [t.text for t in toks]
        assert all(t.norm for t in toks)
