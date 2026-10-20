"""Coach: builds the only cloud payloads (overview.md rule 4), guards async results, judges CHECK answers
locally, and plans Practice. Learner free text is never put into a BrainRequest.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from leafi.core.storage import Store
from leafi.core.text import norm, words
from leafi.services.brain import BrainRequest, Intent
from leafi.study import knowledge
from leafi.study.alignment import ReadingState
from leafi.study.stopwords import STOPWORDS

log = logging.getLogger("leafi.coach")

MAX_PRACTICE = 2
REDACTED = "[name]"


def redact(text: str, terms: Iterable[str]) -> str:
    for t in sorted({t for t in terms if t}, key=len, reverse=True):
        text = re.sub(re.escape(t), REDACTED, text, flags=re.IGNORECASE)
    return text


def sentence_text(page_text: str, state: ReadingState, sid: int) -> str:
    a = state.tokens[state.first_index(sid)].start
    b = state.tokens[state.last_index(sid)].end
    tail = re.match(r"[^\w\s]*", page_text[b:])
    return page_text[a: b + (tail.end() if tail else 0)].strip()


def page_window(page_text: str, state: ReadingState, sids: list[int], max_sentences: int = 3) -> str:
    chosen = [s for s in sids if s in state.sentence_ids()][-max_sentences:]
    return " ".join(sentence_text(page_text, state, s) for s in chosen)


def find_on_page(state: ReadingState, phrase: str) -> str | None:
    """The page's own spelling of `phrase` when it occurs on the page, else None (keeps learner text local)."""
    target = [norm(w) for w in words(phrase)]
    target = [t for t in target if t]
    if not target:
        return None
    n = len(target)
    for i in range(state.n - n + 1):
        if [t.norm for t in state.tokens[i:i + n]] == target:
            return " ".join(t.text for t in state.tokens[i:i + n])
    return None


def explain_request(window: str, target: str | None, terms: Iterable[str], languages=("en", "zh")) -> BrainRequest:
    intent = Intent.EXPLAIN_WORD if target else Intent.EXPLAIN_SENTENCE
    return BrainRequest(intent, redact(window, terms), redact(target, terms) if target else None,
                        languages=tuple(languages))


def questions_request(window: str, terms: Iterable[str]) -> BrainRequest:
    return BrainRequest(Intent.QUESTIONS, redact(window, terms))


# ---------------------------------------------------------------- async guard (ADR-0010 §5/§8)


@dataclass(frozen=True)
class GuardToken:
    session_id: int
    revision_id: int | None
    turn_id: int


class AsyncGuard:
    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        self.revision_id: int | None = None
        self.turn_id = 0

    def update(self, revision_id: int | None, turn_id: int) -> None:
        self.revision_id, self.turn_id = revision_id, turn_id

    def token(self) -> GuardToken:
        return GuardToken(self.session_id, self.revision_id, self.turn_id)

    def is_current(self, tok: GuardToken) -> bool:
        return tok == self.token()


async def enrich(brain, req: BrainRequest, guard: AsyncGuard, deadline_s: float) -> dict | None:
    """Run a Brain request under the deadline; a result is applied only if the guard did not move."""
    tok = guard.token()
    try:
        result = await asyncio.wait_for(brain.run(req), deadline_s)
    except Exception:
        log.warning("brain unavailable", exc_info=True)
        return None
    if result is not None and not guard.is_current(tok):
        log.info("stale brain result discarded (turn moved on)")
        return None
    return result


# ---------------------------------------------------------------- CHECK outcomes (ADR-0013)


def check_outcome(answer: str | None, keyword_sets: list[list[str]], *, skipped: bool = False) -> str:
    """Exhaustive partition: unavailable / correct / incorrect / unavailable (too little to judge)."""
    if answer is None or skipped:
        return "unavailable"
    ws = [norm(w) for w in words(answer)]
    ws = [w for w in ws if w]
    if not ws or " ".join(ws) in ("i don't know", "i do not know", "dont know", "don't know", "idk"):
        return "unavailable"
    present = set(ws)
    for ks in keyword_sets:
        need = [norm(k) for k in ks if norm(k)]
        if need and all(k in present for k in need):
            return "correct"
    if sum(1 for w in ws if w not in STOPWORDS) >= 2:
        return "incorrect"
    return "unavailable"


# ---------------------------------------------------------------- Practice plan


def practice_plan(store: Store, candidates: list[tuple[int, str]]) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """At most two candidates, ordered by Difficulty weight then position; the rest are not practised."""
    ordered = knowledge.practice_order(store, candidates)
    return ordered[:MAX_PRACTICE], ordered[MAX_PRACTICE:]
