"""Answer scores (ADR-0017 §3.4; M7 design D16): pure, local, no model.

A spoken answer counts only when it was confidently recognised (every word ≥ `ANSWER_MIN_CONF`); otherwise the
outcome is `unavailable`, whatever it seems to say (owner decision 6). Typed answers always count.
- `item_said`: success when the answer's content words are exactly the item's words, each by ADR-0013's pair class
  `exact` or `phones` ("through", "it's through" succeed; "I don't know what through means" does not).
- `cloze_word`: success when the answer's content words are exactly the cloze word by the same classes (a
  homophone or the same phones counts: ADR-0013 v2's real-word rule).
- `item_used` is a `judge` call, not here.
Silence or an empty answer is `unavailable`: no retrieval event, no encounter.
"""

from __future__ import annotations

from typing import Literal

from leafi.core.ports import Utterance
from leafi.core.text import norm, words
from leafi.core.wordinfo import NullWordInfo, WordInfo
from leafi.study.alignment import EXACT, PHONES, Tok, pair_class
from leafi.study.function_words import FUNCTION_WORDS, INTERJECTIONS

ANSWER_MIN_CONF = 0.8  # untuned
Outcome = Literal["success", "fail", "unavailable"]


def confident(u: Utterance) -> bool:
    return u.typed or (bool(u.words) and all(w.conf is not None and w.conf >= ANSWER_MIN_CONF for w in u.words))


def _content(text: str) -> list[str]:
    return [n for n in (norm(w) for w in words(text)) if n and n not in FUNCTION_WORDS and n not in INTERJECTIONS]


def _same_words(answer: list[str], target: list[str], info: WordInfo) -> bool:
    if not target or len(answer) != len(target):
        return False
    info.prepare(set(answer) | set(target))
    return all(pair_class(a, Tok(t, t, 0, len(t), 1), info) in (EXACT, PHONES) for a, t in zip(answer, target,
                                                                                                strict=True))


def item_said(u: Utterance | None, item_key: str, info: WordInfo | None = None) -> Outcome:
    if u is None or not u.text.strip() or not confident(u):
        return "unavailable"
    return "success" if _same_words(_content(u.text), _content(item_key) or [norm(item_key)],
                                    info or NullWordInfo()) else "fail"


def cloze_word(u: Utterance | None, cloze: str, info: WordInfo | None = None) -> Outcome:
    if u is None or not u.text.strip() or not confident(u):
        return "unavailable"
    return "success" if _same_words(_content(u.text), [norm(cloze)], info or NullWordInfo()) else "fail"
