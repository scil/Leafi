"""Answer scores (ADR-0017 §3.4; M7 design D16): pure and local, except `item_used`, which is one `judge` call.

A spoken answer counts only when it was confidently recognised (every word ≥ `ANSWER_MIN_CONF`); otherwise the
outcome is `unavailable`, whatever it seems to say (owner decision 6). Typed answers always count.
- `item_said`: success when the answer's content words are exactly the item's words, each by ADR-0013's pair class
  `exact` or `phones` ("through", "it's through" succeed; "I don't know what through means" does not).
- `cloze_word`: success when the answer's content words are exactly the cloze word by the same classes (a
  homophone or the same phones counts: ADR-0013 v2's real-word rule).
- `item_used`: one `judge` call with fixed few-shot examples (`prompts.JUDGE_SYSTEM`); only on an eligible backend.
Silence or an empty answer is `unavailable`: no retrieval event, no encounter.
"""

from __future__ import annotations

import time
from typing import Literal

from leafi.core.ports import Leaf, Section, Utterance
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


VERDICT = {"yes": "success", "no": "fail", "cannot_tell": "unavailable"}


def judge_sections(u: Utterance, item_key: str, prompt: str) -> tuple[Section, ...]:
    """What a `judge` call carries: the item's key (a book field), the prompt Leafi asked (its own line), and the
    learner's answer — a non-book leaf that egress redacts by content (D10, ADR-0021 E1/E2)."""
    return (Section("item", (Leaf(f"word '{item_key}'", book=True),)),
            Section("prompt", (Leaf(prompt),)),
            Section("answer", (Leaf(u.text),)))


async def item_used(s, u: Utterance | None, item_key: str, prompt: str) -> Outcome:
    """`item_used`: one `judge` call (`yes | no | cannot_tell`). An unconfident or empty answer, no eligible
    backend, a timeout or `cannot_tell` → `unavailable` (§3.4)."""
    if u is None or not u.text.strip() or not confident(u) or s.brain is None:
        return "unavailable"
    from leafi.study.brain import call as bc
    from leafi.study.brain import generate, prompts, routing, schemas

    sections = (generate.learner_context(s), *judge_sections(u, item_key, prompt))
    make = prompts.single_request("judge", prompts.JUDGE_SYSTEM, sections, schemas.Judgement,
                                  learner_id=s.learner_id, session_id=s.session_id)
    ctx = generate.context(s, time.monotonic() + routing.moment_s("feedback", s.mouth))
    result = await bc.brain_call(s.brain, ctx, "judge", make, schemas.Judgement.model_validate)
    return "unavailable" if result is None else VERDICT[result.value.verdict]
