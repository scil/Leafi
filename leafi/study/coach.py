"""Coach: builds the Brain's page-text requests (overview.md rule 4; `leafi.privacy.egress` pseudonymises them),
guards async results, judges CHECK answers locally, and plans Practice. Learner free text is never put into a
BrainRequest.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from leafi.core.storage import Store
from leafi.core.text import norm, words
from leafi.services.brain import MAX_WINDOW_CHARS, BrainRequest, Intent
from leafi.study import knowledge
from leafi.study.alignment import ReadingState
from leafi.study.stopwords import STOPWORDS

log = logging.getLogger("leafi.coach")

MAX_PRACTICE = 2


def sentence_text(page_text: str, state: ReadingState, sid: int) -> str:
    a = state.tokens[state.first_index(sid)].start
    b = state.tokens[state.last_index(sid)].end
    tail = re.match(r"[^\w\s]*", page_text[b:])
    return page_text[a: b + (tail.end() if tail else 0)].strip()


def page_window(page_text: str, state: ReadingState, sids: list[int], max_sentences: int = 3,
                max_chars: int = MAX_WINDOW_CHARS) -> str:
    """At most 3 sentences and `max_chars` characters (earliest sentences dropped first, then the last one cut
    at a word boundary), so a valid page never makes an invalid BrainRequest (review 1 #15)."""
    chosen = [sentence_text(page_text, state, s) for s in sids if s in state.sentence_ids()][-max_sentences:]
    while len(chosen) > 1 and len(" ".join(chosen)) > max_chars:
        chosen.pop(0)
    window = " ".join(chosen)
    if len(window) > max_chars:
        window = window[:max_chars].rsplit(" ", 1)[0]
    return window


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


def explain_request(window: str, target: str | None, languages=("en", "zh"), *, learner_id: int | None = None,
                    session_id: int | None = None) -> BrainRequest:
    """Page text only; `leafi.privacy.egress` replaces every protected name when the request is prepared."""
    intent = Intent.EXPLAIN_WORD if target else Intent.EXPLAIN_SENTENCE
    return BrainRequest(intent, window, target, languages=tuple(languages), learner_id=learner_id,
                        session_id=session_id)


def questions_request(window: str, *, learner_id: int | None = None, session_id: int | None = None) -> BrainRequest:
    return BrainRequest(Intent.QUESTIONS, window, learner_id=learner_id, session_id=session_id)


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


def practice_plan(store: Store, learner_id: int, candidates: list[tuple[int, str]]
                  ) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """At most two candidates, ordered by the learner's Difficulty weight then position; the rest are not
    practised."""
    ordered = knowledge.practice_order(store, learner_id, candidates)
    return ordered[:MAX_PRACTICE], ordered[MAX_PRACTICE:]
