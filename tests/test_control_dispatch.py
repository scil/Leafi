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


async def test_a_dead_eye_is_reported_once_per_outage_on_the_face(settings):
    """TD-20: empty frames for EYE_OFFLINE_AFTER polls show one status line; a frame resets it."""
    from leafi.study import session as session_mod

    settings.sentence_pause_s = 0.05
    settings.page_poll_s = 0.01
    store = Store(settings.db_path)
    eye = FakeEye([None])
    tracker = PageTracker(store, eye, MockOcr(), settings, sleep=lambda s: asyncio.sleep(0), settle_frames=1)
    face = RecordingFace()
    hub = Hub(faces={"f": face}, eyes={"desk": eye}, policy="none", study_eye="desk")
    frame = render(PAGES[0], number=1)
    assert session_mod.EYE_OFFLINE_AFTER * settings.page_poll_s < 0.5  # both outages outlast the threshold
    script = [0.05] * 20 + [lambda: eye.show(frame), 0.1, lambda: eye.show(None)] + [0.05] * 20 + ["/stop"]
    s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(unavailable=True),
                     listener=SlowVoice(script, voice=True), page_tracker=tracker, ocr=MockOcr())
    await asyncio.wait_for(s.run(book_title="B", page_text=PAGE, page_number=1), 20)
    offline = [d for d in face.shown if d.kind == "status" and "camera" in d.text.lower()]
    assert len(offline) == 2, [d.text for d in face.shown]


async def test_a_timed_out_listen_does_not_answer_the_next_listen(settings):
    """Review 2 D1: the pause that completes a sentence must not hand PRACTICE an instant timeout."""
    settings.sentence_pause_s = 0.1
    settings.practice_retry_s = 5
    store = Store(settings.db_path)
    listener = SlowVoice([_voice("The dog red"), 0.1, _voice("ran"), "/stop"], voice=True)
    s = StudySession(store=store, hub=Hub(faces={"f": RecordingFace()}, policy="none"), settings=settings,
                     brain=MockBrain(unavailable=True), listener=listener)
    await asyncio.wait_for(s.run(book_title="B", page_text="The dog ran far.", page_number=1), 10)
    rows = {r["expected"]: (r["status"], r["withdrawn_reason"] or r["unsure_reason"])
            for r in store.all("SELECT * FROM miscues")}
    assert rows == {"ran": ("withdrawn", "practice")}
    assert 5.0 in listener.timeouts


async def test_cancelling_the_session_during_playback_stops_the_speaker(settings, tmp_path):
    """Review 2 D5: a cancelled run() (Ctrl-C) must not leave the clip playing."""
    started = asyncio.Event()

    class Log(list):
        def append(self, item):
            super().append(item)
            if item == ("start", "mouth"):
                started.set()

    log = Log()
    mouth = FakeMouth(hang=True, log=log)
    hub = Hub(faces={"f": RecordingFace()}, mouths={"pc": mouth}, synthesizer=FakeSynth(tmp_path), policy="all")
    s = StudySession(store=Store(settings.db_path), hub=hub, settings=settings, brain=MockBrain(),
                     listener=ScriptedListener([], voice=True), control_source=ConsoleOnce([]))
    task = asyncio.create_task(s.run(book_title="B", page_text=PAGE, page_number=1))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0)
    assert mouth.stopped >= 1 and ("end", "mouth") in log
    assert not hub._lock.locked() and not s.gate._lock.locked()


async def test_a_page_turn_during_review_is_handled_in_read_without_no_op_lines(settings):
    """Review 2 D6: no page watching in REVIEW_DUE; the turn is picked up once READ starts."""
    from leafi.study import anki
    from tests.fakes.anki import FakeAnki

    class DelayedVoice(SlowVoice):
        async def next_utterance(self, timeout_s):
            while self.script and callable(self.script[0]):
                self.script.pop(0)()
            if self.script and isinstance(self.script[0], tuple):
                delay, text = self.script.pop(0)
                await asyncio.sleep(delay)
                return typed_utterance(text)
            return await super().next_utterance(timeout_s)

    settings.sentence_pause_s = 0.05
    settings.page_poll_s = 0.02
    store = Store(settings.db_path)
    fake = FakeAnki()
    fake.add_due_card("blew")
    eye = FakeEye([render(PAGES[0], number=1)])
    tracker = PageTracker(store, eye, MockOcr(), settings, sleep=lambda s: asyncio.sleep(0), settle_frames=1)
    face = RecordingFace()
    hub = Hub(faces={"f": face}, eyes={"desk": eye}, policy="none", study_eye="desk")
    script = [lambda: eye.show(render(PAGES[1], number=2)), (0.3, "good")] + [0.05] * 40 + ["/stop"]
    s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(unavailable=True),
                     listener=DelayedVoice(script, voice=True), page_tracker=tracker, ocr=MockOcr(),
                     anki_client=anki.AnkiClient(transport=fake.transport()))
    await asyncio.wait_for(s.run(book_title="Kite", page_number=1), 20)
    assert "That doesn't do anything right now." not in face.texts
    assert store.one("SELECT ease FROM review_answers")["ease"] == 3
    assert s.flags.transitions.count("FIND_PAGE") == 2
