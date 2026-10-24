"""Text helpers shared by alignment, corrections and the lexicon.

`norm()` is versioned with `TOKENIZER_VERSION` (ADR-0013 Definitions); a change to the tokeniser or the
normalisation tables MUST bump it, because stored token indexes are only meaningful for one version.
Spans are half-open Unicode code-point offsets `[start, end)` (ADR-0010 §6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .ports import Utterance, Word

TOKENIZER_VERSION = "2"  # v2: numeral readings through num2words (ADR-0013 → norm() v2); boundaries as v1

_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’\-][0-9A-Za-zÀ-ÖØ-öø-ÿ]+)*")
_SENT_END_RE = re.compile(r"^[\"'”’)\]]*[.?!]")

# ASR output often drops apostrophes; both sides map to one spelling.
CONTRACTIONS = {
    "dont": "don't", "cant": "can't", "wont": "won't", "isnt": "isn't", "arent": "aren't",
    "didnt": "didn't", "doesnt": "doesn't", "wasnt": "wasn't", "werent": "weren't", "im": "i'm",
    "ive": "i've", "youre": "you're", "theyre": "they're", "thats": "that's", "whats": "what's",
    "lets": "let's", "couldnt": "couldn't", "shouldnt": "shouldn't", "wouldnt": "wouldn't",
    "hasnt": "hasn't", "havent": "haven't", "hadnt": "hadn't", "ill": "i'll", "youll": "you'll",
    "theyll": "they'll", "id": "i'd", "youd": "you'd", "theyd": "they'd",
}

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
         "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORDINALS = ["zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
             "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth",
             "seventeenth", "eighteenth", "nineteenth", "twentieth", "thirtieth", "fortieth", "fiftieth",
             "sixtieth", "seventieth", "eightieth", "ninetieth", "hundredth", "thousandth", "millionth"]
# Words a `number join` may consist of (ADR-0013 rule 3); "and" only between two of them.
NUMBER_WORDS = frozenset(_ONES + _TENS + _ORDINALS + ["hundred", "thousand", "million"])
_ORDINAL_RE = re.compile(r"^(\d+)(st|nd|rd|th)$")


def canonical_number(text: str) -> str:
    """ADR-0013 canonical form of a number reading: lowercase, no "and", commas, spaces or hyphens."""
    w = text.lower().replace(",", " ").replace("-", " ").split()
    return "".join(x for x in w if x != "and")


def numeral_readings(word: str) -> frozenset[str]:
    """Every reading `num2words` gives a numeral token, in canonical form; empty for a non-numeral."""
    w = word.lower().replace(",", "")
    m = _ORDINAL_RE.match(w)
    if not (w.isdigit() or m):
        return frozenset()
    from num2words import num2words  # LGPL-2.1, imported only when a numeral occurs

    if m:
        return frozenset({canonical_number(num2words(int(m.group(1)), to="ordinal"))})
    n = int(w)
    out = {canonical_number(num2words(n))}
    if len(w) == 4 and 1100 <= n <= 2099:
        out.add(canonical_number(num2words(n, to="year")))
    return frozenset(out)


def norm(word: str) -> str:
    """Lowercase, unify apostrophes, strip punctuation and hyphens, numerals → their cardinal (or ordinal)
    reading in canonical form, contractions table."""
    w = word.lower().replace("’", "'").strip(".,;:!?\"()[]{}“”‘'-—–…")
    if w.isdigit() or _ORDINAL_RE.match(w):
        from num2words import num2words

        m = _ORDINAL_RE.match(w)
        return canonical_number(num2words(int(m.group(1)), to="ordinal") if m else num2words(int(w)))
    w = w.replace("-", "")
    return CONTRACTIONS.get(w, w)


def sim(a: str, b: str) -> float:
    """ADR-0013: `rapidfuzz.fuzz.ratio(a, b) / 100` on normalised strings."""
    return fuzz.ratio(a, b) / 100.0


@dataclass(frozen=True)
class TextToken:
    text: str
    norm: str
    start: int
    end: int
    sentence_id: int  # 1-based


def words(text: str) -> list[str]:
    """Surface words of free text (typed utterances, OCR lines)."""
    return _WORD_RE.findall(text)


def tokenize(text: str) -> list[TextToken]:
    """Expected tokens of a page revision with sentence ids and char spans.

    A sentence ends after a token that is followed (before the next token) by `.`, `?` or `!`, optionally
    after closing quotes/brackets. Text without terminal punctuation is one sentence.
    """
    out: list[TextToken] = []
    sid = 1
    matches = list(_WORD_RE.finditer(text))
    for k, m in enumerate(matches):
        out.append(TextToken(m.group(0), norm(m.group(0)), m.start(), m.end(), sid))
        nxt = matches[k + 1].start() if k + 1 < len(matches) else len(text)
        gap = text[m.end():nxt].lstrip()
        if _SENT_END_RE.match(gap) and k + 1 < len(matches):
            sid += 1
    return out


def sentences(tokens: list[TextToken]) -> dict[int, tuple[int, int]]:
    """sentence_id -> (first_index, last_index) inclusive."""
    out: dict[int, tuple[int, int]] = {}
    for i, t in enumerate(tokens):
        first, _ = out.get(t.sentence_id, (i, i))
        out[t.sentence_id] = (first, i)
    return out


def ends_sentence(text: str) -> bool:
    s = text.rstrip().rstrip("\"'”’)]")
    return s == "" or s.endswith((".", "?", "!"))


def typed_utterance(text: str, source: str = "console") -> Utterance:
    """A typed Utterance: words without timestamps or confidence, no audio (B11)."""
    return Utterance(text=text, words=[Word(w) for w in words(text)], typed=True,
                     line_end=ends_sentence(text), source=source)
