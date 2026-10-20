"""Interrupted session: closed on the next start, resumed from the committed cursor (ADR-0013)."""

from __future__ import annotations

import pytest

from leafi.core.hub import Hub
from leafi.core.storage import Store, loads
from leafi.services.brain.mock import MockBrain
from leafi.study.alignment import ReadingState
from leafi.study.session import StudySession
from tests.fakes import RecordingFace, ScriptedListener
from tests.test_study_text_mode import PAGE, _miscues


async def test_interrupted_session_is_closed_and_resumed_from_the_committed_cursor(settings):
    class Crash(Exception):
        pass

    class CrashingListener(ScriptedListener):
        async def next_utterance(self, timeout_s):
            if not self.script:
                raise Crash()
            return await super().next_utterance(timeout_s)

    store = Store(settings.db_path)
    hub = Hub(faces={"c": RecordingFace()}, policy="none")
    first = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                         listener=CrashingListener(["The cat sat on the hat by the door.", "Mia saw a big"]))
    with pytest.raises(Crash):
        await first.run(book_title="Fixture", page_text=PAGE, page_number=1)
    assert store.one("SELECT ended_at FROM reading_sessions")["ended_at"] is None

    second = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                          listener=ScriptedListener(["yes", "brown fox.", "/stop"]))
    await second.run(book_title="Fixture", page_text=PAGE, page_number=1)
    s1 = store.one("SELECT * FROM reading_sessions WHERE id=1")
    assert loads(s1["summary"])["interrupted"] is True
    assert _miscues(store)["small"] == ("unsure", "interrupted", "none")
    reads = store.all("SELECT * FROM page_reads ORDER BY id")
    assert [r["attempt"] for r in reads] == [1, 2]
    st = ReadingState.from_json(PAGE, loads(reads[1]["reading_state"]))
    assert st.statuses().split()[:13] == ["C"] * 13  # resumed at old ccur 13, then "brown fox." read
    assert 1 in st.completed and 2 in st.completed


async def test_a_rejected_second_launch_leaves_the_live_session_untouched(settings, monkeypatch):
    from leafi.core import lease as speech_lease
    from leafi.study import session as session_module
    from tests import seed

    store = Store(settings.db_path)
    book, page, rev = seed.book_page(store, PAGE, source="manual")
    live = seed.session(store, book)
    read = seed.page_read(store, live, page, rev)
    mid = seed.miscue(store, read, rev, PAGE, "hat")

    def held(*a, **k):
        raise speech_lease.LeaseHeld("speech lease held by pid 4242")

    monkeypatch.setattr(session_module.speech_lease, "acquire", held)
    second = StudySession(store=store, hub=Hub(faces={"c": RecordingFace()}, policy="none"), settings=settings,
                          brain=MockBrain(), listener=ScriptedListener(["/stop"]))
    with pytest.raises(speech_lease.LeaseHeld):
        await second.run(book_title="Fixture", page_text=PAGE, page_number=1)
    assert store.one("SELECT ended_at FROM reading_sessions WHERE id=?", (live,))["ended_at"] is None
    assert seed.status_of(store, mid) == ("candidate", None)
    assert store.one("SELECT COUNT(*) AS n FROM reading_sessions")["n"] == 1
