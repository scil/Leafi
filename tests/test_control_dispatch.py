"""Persistent control dispatch (review 1 #7, #20): console /stop and /skip during playback, physical page turns."""

from __future__ import annotations

import asyncio

from leafi.core.hub import Hub
from leafi.core.ports import Utterance, Word
from leafi.core.storage import Store, loads
from leafi.core.text import typed_utterance
from leafi.services.brain.mock import MockBrain
from leafi.services.ocr.mock import MockOcr
from leafi.study.page_tracker import PageTracker
from leafi.study.session import StudySession
from tests.fakes import FakeMouth, FakeSynth, RecordingFace, ScriptedListener
from tests.fixtures.pages import PAGES, FakeEye, render

PAGE = "The dog ran far. The cat sat."


class ConsoleOnce:
    """A console that yields its lines one by one, then blocks like a terminal with nobody typing."""

    is_voice = False

    def __init__(self, lines, delay_s=0.1):
        self.lines = list(lines)
        self.delay_s = delay_s

    async def next_utterance(self, timeout_s):
        if self.lines:
            await asyncio.sleep(self.delay_s)  # typed while Leafi is talking
            return typed_utterance(self.lines.pop(0))
        await asyncio.sleep(3600)

    async def pause(self):
        return None

    async def resume(self, after_s=0.0):
        return None


def _voice(text: str) -> Utterance:
    return Utterance(text, [Word(w) for w in text.split()], typed=False)


async def test_console_stop_during_playback_cancels_speech_and_wraps(settings, tmp_path):
    store = Store(settings.db_path)
    mouth = FakeMouth(play_s=30)
    hub = Hub(faces={"f": RecordingFace()}, mouths={"pc": mouth}, synthesizer=FakeSynth(tmp_path), policy="all")
    s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                     listener=ScriptedListener([], voice=True), control_source=ConsoleOnce(["/stop"]))
    await asyncio.wait_for(s.run(book_title="B", page_text=PAGE, page_number=1), 10)
    assert mouth.stopped >= 1
    assert s.flags.transitions[-1] == "WRAP" and s.flags.stopped
    assert loads(store.one("SELECT summary FROM reading_sessions")["summary"])["stopped"] is True


async def test_console_skip_during_playback_cancels_only_the_current_line(settings, tmp_path):
    store = Store(settings.db_path)
    mouth = FakeMouth(play_s=0.2)
    hub = Hub(faces={"f": RecordingFace()}, mouths={"pc": mouth}, synthesizer=FakeSynth(tmp_path), policy="all")
    s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                     listener=ScriptedListener([_voice("The dog ran far"), "/stop"], voice=True),
                     control_source=ConsoleOnce(["/skip"]))
    await asyncio.wait_for(s.run(book_title="B", page_text=PAGE, page_number=1), 10)
    assert mouth.stopped >= 1          # the first line was cut
    assert len(mouth.played) >= 3      # later lines still played
    assert store.one("SELECT COUNT(*) AS n FROM observations")["n"] == 4  # reading continued


class SlowVoice(ScriptedListener):
    """Voice listener whose float items are silences of that many seconds; callables run as side effects."""

    async def next_utterance(self, timeout_s):
        while self.script and callable(self.script[0]):
            self.script.pop(0)()
        if self.script and isinstance(self.script[0], float):
            await asyncio.sleep(self.script.pop(0))
            return None
        return await super().next_utterance(timeout_s)


async def test_a_physical_page_turn_settles_candidates_and_finds_the_new_page(settings):
    settings.sentence_pause_s = 0.05
    settings.page_poll_s = 0.02
    store = Store(settings.db_path)
    eye = FakeEye([render(PAGES[0], number=1)])
    tracker = PageTracker(store, eye, MockOcr(), settings, sleep=lambda s: asyncio.sleep(0), settle_frames=1)
    hub = Hub(faces={"f": RecordingFace()}, eyes={"desk": eye}, policy="none", study_eye="desk")
    script = [_voice("Tom hid"), 0.05, lambda: eye.show(render(PAGES[1], number=2))] + [0.05] * 40 + [
        "/stop"]
    s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(unavailable=True),
                     listener=SlowVoice(script, voice=True), page_tracker=tracker, ocr=MockOcr())
    await asyncio.wait_for(s.run(book_title="Kite", page_number=1), 20)
    rows = {r["expected"]: (r["status"], r["unsure_reason"]) for r in store.all("SELECT * FROM miscues")}
    assert rows == {"had": ("unsure", "skipped")}
    printed = [r["printed_number"] for r in store.all(
        "SELECT p.printed_number FROM page_reads pr JOIN pages p ON p.id = pr.page_id ORDER BY pr.id")]
    assert printed == [1, 2], (s.flags.transitions, hub.faces["f"].texts)
    assert s.flags.transitions.count("FIND_PAGE") == 2
