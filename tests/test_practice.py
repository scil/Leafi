"""Practice rules (ADR-0013 → Practice): ≤ 2 retries, skip always, idle, not_practised, confirmed only with
acoustic evidence, stop/back during practice."""

from __future__ import annotations

from leafi.core.hub import Hub
from leafi.core.ports import AudioRef, Utterance, Word
from leafi.core.storage import Store
from leafi.services.brain.mock import MockBrain
from leafi.services.pronunciation.mock import MockScorer
from leafi.study.session import StudySession
from tests.fakes import RecordingFace, ScriptedListener

PAGE = "The dog ran far. The cat sat."


def _voice(text: str) -> Utterance:
    return Utterance(text, [Word(w) for w in text.split()], typed=False, audio_ref=AudioRef(b"\x01\x00" * 800))


async def _run(settings, script, voice=False, pron=None):
    store = Store(settings.db_path)
    listener = ScriptedListener(script, voice=voice)
    s = StudySession(store=store, hub=Hub(faces={"f": RecordingFace()}, policy="none"), settings=settings,
                     brain=MockBrain(unavailable=True), listener=listener, pron=pron)
    await s.run(book_title="P", page_text=PAGE, page_number=1)
    rows = {r["expected"]: (r["status"], r["withdrawn_reason"] or r["unsure_reason"], r["evidence"])
            for r in store.all("SELECT * FROM miscues")}
    prac = [(r["attempt"], r["outcome"], r["evidence"]) for r in store.all("SELECT * FROM practices ORDER BY id")]
    return rows, prac, listener


async def test_two_disagreements_make_unsure_and_never_confirmed_in_text_mode(settings):
    settings.pron_auto_judge = True  # irrelevant without audio
    rows, prac, _ = await _run(settings, ["The dog red far.", "rod", "rod", "/stop"], pron=MockScorer(0.1))
    assert rows == {"ran": ("unsure", "disagreed", "none")}
    assert prac == [(1, "disagreed", "none"), (2, "disagreed", "none")]


async def test_matching_retry_withdraws_in_text_mode(settings):
    rows, prac, _ = await _run(settings, ["The dog red far.", "red", "ran", "/stop"])
    assert rows == {"ran": ("withdrawn", "practice", "none")}
    assert prac == [(1, "disagreed", "none"), (2, "matched", "none")]


async def test_voice_idle_retry_is_unsure_idle_and_uses_the_practice_timer(settings):
    script = [_voice("The dog red far"), None, None, "/stop"]
    rows, prac, listener = await _run(settings, script, voice=True)
    assert rows == {"ran": ("unsure", "idle", "none")}
    assert prac == []
    assert settings.practice_retry_s in listener.timeouts


async def test_acoustic_evidence_can_confirm_only_when_auto_judge_is_on(settings):
    script = [_voice("The dog red far"), _voice("red"), _voice("red"), "/stop"]
    rows, prac, _ = await _run(settings, script, voice=True, pron=MockScorer(0.1))
    assert rows == {"ran": ("unsure", "disagreed", "none")}  # PRON_AUTO_JUDGE off by default
    settings.pron_auto_judge = True
    settings.data_dir = settings.data_dir.parent / "data2"
    rows, prac, _ = await _run(settings, script, voice=True, pron=MockScorer(0.1))
    assert rows == {"ran": ("confirmed", None, "acoustic")}
    assert prac == [(1, "disagreed", "acoustic"), (2, "disagreed", "acoustic")]


async def test_more_than_two_candidates_are_not_practised(settings):
    rows, prac, _ = await _run(settings, ["The dig red for.", "/skip", "/skip", "/stop"])
    assert rows["dog"] == ("unsure", "skipped", "none")
    assert rows["ran"] == ("unsure", "skipped", "none")
    assert rows["far"] == ("unsure", "not_practised", "none")
    assert prac == [(1, "skipped", "none"), (1, "skipped", "none")]


async def test_stop_during_practice_settles_every_open_candidate(settings):
    rows, _, _ = await _run(settings, ["The dog red far.", "/stop"])
    assert rows == {"ran": ("unsure", "skipped", "none")}


async def test_back_during_practice_aborts_it_and_reopens(settings):
    rows, _, _ = await _run(settings, ["The dig ran far.", "/back", "The dog ran far.", "/stop"])
    assert rows == {"dog": ("unsure", "skipped", "none")}
