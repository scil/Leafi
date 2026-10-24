"""Mock Brain: deterministic replies built from the request; records every request."""

from __future__ import annotations

from collections.abc import Callable

from leafi.core.text import norm, words
from leafi.services.brain import BrainRequest, Intent, validate

STOP = {"the", "and", "was", "with", "that", "this", "from", "they", "there", "were", "have"}


def _key_word(window: str) -> str:
    cands = [w for w in words(window) if len(w) >= 4 and norm(w) not in STOP]
    return max(cands, key=len) if cands else (words(window) or ["page"])[0]


def default_reply(req: BrainRequest) -> dict:
    if req.intent in (Intent.EXPLAIN_WORD, Intent.EXPLAIN_SENTENCE):
        target = req.target or "this sentence"
        return {"meaning_en": f"\"{target}\" is explained simply here.", "meaning_zh": "这是一个简单的解释。",
                "example": f"I can use \"{target}\" in a sentence.", "follow_up": "", "action": "explain"}
    if req.intent is Intent.QUESTIONS:
        key = _key_word(req.window)
        return {"questions": [{"question": f"Which word from the page goes with \"{key[:2]}...\"?",
                               "answer": f"The word is {key}.", "keywords": [[norm(key)]], "item_key": key}],
                "action": "ask"}
    return {"line": "Nice work, teammate!", "action": "encourage"}


class MockBrain:
    def __init__(self, reply: Callable[[BrainRequest], dict | None] | dict | None = None,
                 unavailable: bool = False) -> None:
        self.reply = reply
        self.unavailable = unavailable
        self.requests: list[BrainRequest] = []

    async def run(self, req: BrainRequest) -> dict | None:
        self.requests.append(req)
        if self.unavailable:
            return None
        if callable(self.reply):
            data = self.reply(req)
        elif isinstance(self.reply, dict):
            data = self.reply.get(req.intent, default_reply(req))
        else:
            data = default_reply(req)
        return validate(req.intent, data) if data is not None else None


class MockModel:
    """The M7 port's mock (design D5): replies by purpose (a value, or a callable of the request); records every
    request; never leaves the process. Used by `--mock` sessions and the tests."""

    locality_destination = "mock"
    host = None

    def __init__(self, replies: dict | None = None, name: str = "mock") -> None:
        self.name, self.replies, self.requests = name, dict(replies or {}), []
        self.needs_reset = False

    async def call(self, req):
        from leafi.core.ports import CallRecord

        self.requests.append(req)
        sent = {"model": req.model, "purpose": req.purpose,
                "turns": [[leaf.value for s in t.sections for leaf in s.leaves] for t in req.turns]}
        req.attempt.sent, req.attempt.model = sent, req.model
        reply = self.replies.get(req.purpose)
        value = reply(req) if callable(reply) else reply
        if value is None:
            return CallRecord("failed", sent=sent, model=req.model, detail="no scripted reply")
        return CallRecord("ok", value=value, sent=sent, model=req.model, provider="mock", transmissions=1)

    async def reset(self) -> None:
        self.needs_reset = False


def create(settings, reply=None, unavailable: bool = False) -> MockBrain:
    return MockBrain(reply, unavailable)
