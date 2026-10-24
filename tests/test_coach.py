"""Coach: cloud payload building, async guard, CHECK partition, Brain fallback, Brain request validation."""

from __future__ import annotations

import pytest

from leafi.services.brain import BrainRequest, Intent, validate
from leafi.services.brain.claude import ClaudeBrain
from leafi.services.brain.mock import MockBrain
from leafi.study import coach, phrases
from leafi.study.alignment import ReadingState

PAGE = "This book belongs to Zephyrine. The fox ran home. It was late."


def test_check_outcomes_are_an_exhaustive_partition():
    keys = [["fox"], ["red", "fox"]]
    assert coach.check_outcome(None, keys) == "unavailable"  # no answer in time
    assert coach.check_outcome("fox", keys, skipped=True) == "unavailable"
    assert coach.check_outcome("I don't know", keys) == "unavailable"
    assert coach.check_outcome("It was a fox!", keys) == "correct"
    assert coach.check_outcome("a big brown dog", keys) == "incorrect"  # ≥ 2 content words
    assert coach.check_outcome("dog", keys) == "unavailable"  # too little to judge
    assert coach.check_outcome("it is the", keys) == "unavailable"


def test_the_page_window_is_page_text_only_and_names_the_learner_for_attribution():
    """Names are replaced by egress when the request is prepared (tests/test_privacy.py), not here."""
    st = ReadingState.from_text(PAGE)
    window = coach.page_window(PAGE, st, [1, 2, 3])
    req = coach.explain_request(window, None, learner_id=7, session_id=3)
    assert req.window in PAGE.replace("\n", " ") or all(s in PAGE for s in req.window.split(". "))
    assert (req.intent, req.learner_id, req.session_id) == (Intent.EXPLAIN_SENTENCE, 7, 3)


def test_find_on_page_returns_page_spelling_or_none():
    st = ReadingState.from_text(PAGE)
    assert coach.find_on_page(st, "FOX ran") == "fox ran"
    assert coach.find_on_page(st, "my school") is None


def test_brain_request_rejects_non_text_payloads():
    with pytest.raises(ValueError):
        BrainRequest(Intent.QUESTIONS, "One. Two. Three. Four.")
    with pytest.raises(TypeError):
        BrainRequest(Intent.EXPLAIN_WORD, "Fox.", target=b"\x00audio")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BrainRequest(Intent.QUESTIONS, "Fox.", summary=(("name", "Zephyrine"),))  # type: ignore[arg-type]


def test_validation_drops_extra_fields_and_disallowed_actions():
    ok = {"meaning_en": "a", "meaning_zh": "", "example": "b", "follow_up": "", "action": "explain"}
    assert validate(Intent.EXPLAIN_WORD, ok) == ok
    assert validate(Intent.EXPLAIN_WORD, {**ok, "action": "send_email"}) is None
    assert validate(Intent.EXPLAIN_WORD, {**ok, "tool": "x"}) is None
    three = {"questions": [{"question": "q", "answer": "a", "keywords": [["k"]], "item_key": "k"}] * 3,
             "action": "ask"}
    assert validate(Intent.QUESTIONS, three) is None


async def test_brain_unavailable_returns_none():
    guard = coach.AsyncGuard(1)
    req = coach.questions_request("The fox ran home.")
    assert await coach.enrich(MockBrain(unavailable=True), req, guard, 1.0) is None


async def test_claude_backend_without_key_is_unavailable(settings):
    brain = ClaudeBrain(settings)
    assert await brain.run(coach.questions_request("The fox ran home.")) is None


async def test_claude_backend_validates_and_never_retries_itself(settings):
    """M5c: one attempt per request from the backend (the mediator owns the one retry); an invalid reply is
    dropped, not asked again."""
    from leafi.core import learner_store
    from leafi.core.storage import Store
    from leafi.privacy import settings as privacy
    from tests.egress_helpers import mock_egress

    class Msg:
        def __init__(self, text):
            self.content = [type("B", (), {"type": "text", "text": text})()]
            self.stop_reason = "end_turn"

    class Client:
        def __init__(self, replies):
            self.replies = list(replies)
            self.calls = []
            self.messages = self

        async def create(self, **kw):
            self.calls.append(kw)
            return Msg(self.replies.pop(0))

    settings.anthropic_api_key = "test-key"
    with Store(settings.db_path) as store:
        lid = learner_store.create(store, "Learner")
        privacy.set_school(store, lid, None)
    e = mock_egress(settings, lambda r: None)
    good = '{"line": "Nice!", "action": "encourage"}'
    client = Client(['{"line": "x", "action": "rm -rf"}', good])
    brain = ClaudeBrain(settings, client, egress=e)
    assert await brain.run(BrainRequest(Intent.ENCOURAGE, "The fox ran home.", learner_id=lid)) is None
    assert len(client.calls) == 1
    assert await brain.run(BrainRequest(Intent.ENCOURAGE, "The fox ran home.", learner_id=lid)) == {
        "line": "Nice!", "action": "encourage"}
    params = client.calls[0]
    assert params["model"] == "claude-opus-5-5"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "<page>" in params["messages"][0]["content"]
    assert "x-leafi-token" in params["extra_headers"]



def test_static_phrases_are_coach_voice_and_pass_the_deny_list():
    for key, variants in phrases.LINES.items():
        for v in variants:
            assert phrases.safe(v), (key, v)
    assert phrases.safe_or("That was wrong.", "practice_again") in phrases.LINES["practice_again"]


def test_study_brain_uses_study_brain_model_not_the_habit_brain_model(monkeypatch):
    """The habit track's BRAIN_MODEL (a Haiku model on this PC) must not leak into the study Brain."""
    from leafi.core.config import Settings

    monkeypatch.setenv("BRAIN_MODEL", "claude-haiku-4-5")
    monkeypatch.delenv("STUDY_BRAIN_MODEL", raising=False)
    s = Settings(_env_file=None)
    assert s.study_brain_model == "claude-opus-5-5"
    params = ClaudeBrain(s).request_params(BrainRequest(Intent.ENCOURAGE, "The fox ran home."))
    assert params["model"] == "claude-opus-5-5"
    monkeypatch.setenv("STUDY_BRAIN_MODEL", "claude-sonnet-5-5")
    assert ClaudeBrain(Settings(_env_file=None)).model == "claude-sonnet-5-5"
