"""Whole sessions on the harness loop (plan M6f): the v1 session's behaviour that ADR-0013/0017/0018 keep, ported
from the removed v1 tests. Never mocked: real Store, scripted inputs; nothing speaks on the camera."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from leafi.core.hub import Hub
from leafi.core.ports import AudioRef, ListenerLost, Utterance, Word
from leafi.core.storage import Store, loads
from leafi.services.pronunciation.mock import MockScorer
from leafi.study import pages, records
from leafi.study.alignment import ReadingState
from tests.fakes import FakeMouth, FakeSynth, RecordingFace, ScriptedListener
from tests.harness_session import activities, env, run, summary

P1 = Path("tests/fixtures/pages/p1.txt").read_text(encoding="utf-8")
DOG = "The dog ran far. The cat sat."


def _voice(text: str) -> Utterance:
    return Utterance(text, [Word(w) for w in text.split()], typed=False, audio_ref=AudioRef(b"\x01\x00" * 800))


def _miscues(store) -> dict:
    return {r["expected"]: (r["status"], r["withdrawn_reason"] or r["unsure_reason"] or r["invalidated_reason"],
                            r["evidence"]) for r in store.all("SELECT * FROM miscues ORDER BY id")}


# ---------------------------------------------------------------- reading


async def test_stop_mid_sentence_completes_it_and_settles_open_candidates_as_skipped(settings):
    e = env(settings, [None, "The cat sat on the mat", "/stop"], page=P1, learner="Ada")
    await run(e)
    assert _miscues(e.store) == {"hat": ("unsure", "skipped", "none")}
    assert e.store.one("SELECT tokens_unread FROM page_reads")["tokens_unread"] == 3  # "by the door"


async def test_control_precedence_wins_over_page_text_except_beyond_six_words(settings):
    page = "Stop and look both ways. Then stop at home and rest."
    e = env(settings, [None, "Stop"], page=page, learner="Ada")
    sid = await run(e)
    assert summary(e.store, sid)["end"] == "stop"
    assert e.store.one("SELECT COUNT(*) AS n FROM utterances WHERE kind='reading'")["n"] == 0
    settings.data_dir = settings.data_dir.parent / "data2"
    e = env(settings, [None, "Stop and look both ways then stop", "/stop"], page=page, learner="Ada")
    await run(e)
    assert [r["kind"] for r in e.store.all("SELECT kind FROM utterances ORDER BY id")] == ["reading"]


async def test_page_ready_tells_a_typing_learner_to_type_and_a_reader_to_read(settings):
    e = env(settings, [None, "/stop"], learner="Ada")
    await run(e)
    assert any("Type each sentence" in t for t in e.face.texts)
    settings.data_dir = settings.data_dir.parent / "data2"
    e = env(settings, [], listener=ScriptedListener([None, "/stop"], voice=True), learner="Ada")
    await run(e)
    assert any("Read it aloud" in t or "Off you go" in t for t in e.face.texts)


async def test_candidates_keep_their_evidence_after_a_correction_shifts_token_indexes(settings):
    """"The" → "The small" moves `ran` from index 2 to 3; its candidate must still be found (by miscue_id)."""
    e = env(settings, [None, "The dog red", "/fix The The small", "The small dog ran far.", "/stop"],
            page="The dog ran far.", learner="Ada")
    await run(e)
    assert {k: v[:2] for k, v in _miscues(e.store).items()} == {"ran": ("withdrawn", "self_corrected")}


async def test_the_session_identifies_the_book_and_page_from_the_camera(settings):
    from leafi.services.catalog.mock import MockCatalog
    from leafi.services.ocr.mock import MockOcr
    from leafi.study.page_tracker import PageTracker
    from tests.fixtures.pages import PAGES, FakeEye, render

    async def nosleep(_):
        return None

    store = Store(settings.db_path)
    eye = FakeEye([render("Cover", isbn="9780140328721"), render(PAGES[0], number=3)])
    ocr = MockOcr()
    listener = ScriptedListener(["yes", None, "Tom had a red kite.", "/stop"])
    face = RecordingFace()
    hub = Hub(faces={"f": face}, eyes={"desk_cam": eye}, policy="none", study_eye="desk_cam",
              listeners={"console": listener})
    from leafi.study.harness import loop

    e = loop.Env(store=store, hub=hub, settings=settings, listener=listener, learner="Ada", ocr=ocr,
                 catalog=MockCatalog({"9780140328721": "Kite Day"}),
                 page_tracker=PageTracker(store, eye, ocr, settings, sleep=nosleep))
    await run(e)
    assert tuple(store.one("SELECT title, isbn FROM books")) == ("Kite Day", "9780140328721")
    assert store.one("SELECT printed_number FROM pages")["printed_number"] == 3
    assert any("Kite Day" in t for t in face.texts)
    assert store.one("SELECT COUNT(*) AS n FROM observations")["n"] == 5


# ---------------------------------------------------------------- practice


async def test_acoustic_evidence_confirms_only_when_auto_judge_is_on(settings):
    script = [None, _voice("The dog red far"), _voice("The cat sat"), None, _voice("red"), _voice("red"), "/stop"]
    e = env(settings, [], page=DOG, learner="Ada", listener=ScriptedListener(list(script), voice=True),
            pron=MockScorer(0.1))
    await run(e)
    assert _miscues(e.store) == {"ran": ("unsure", "disagreed", "none")}  # PRON_AUTO_JUDGE off by default
    settings.pron_auto_judge = True
    settings.data_dir = settings.data_dir.parent / "data2"
    e = env(settings, [], page=DOG, learner="Ada", listener=ScriptedListener(list(script), voice=True),
            pron=MockScorer(0.1))
    await run(e)
    assert _miscues(e.store) == {"ran": ("confirmed", None, "acoustic")}
    prac = [(r["attempt"], r["outcome"], r["evidence"]) for r in e.store.all("SELECT * FROM practices ORDER BY id")]
    assert prac == [(1, "disagreed", "acoustic"), (2, "disagreed", "acoustic")]


async def test_text_mode_never_confirms(settings):
    settings.pron_auto_judge = True  # irrelevant without audio
    e = env(settings, [None, "The dog red far.", "The cat sat.", None, "rod", "rod", "/stop"], page=DOG,
            learner="Ada", pron=MockScorer(0.1))
    await run(e)
    assert _miscues(e.store) == {"ran": ("unsure", "disagreed", "none")}


async def test_skip_always_wins_even_when_skip_is_the_practised_word(settings):
    e = env(settings, [None, "Do not slip lines.", None, "skip", "/stop"], page="Do not skip lines.", learner="Ada")
    await run(e)
    assert {k: v[:2] for k, v in _miscues(e.store).items()} == {"skip": ("unsure", "skipped")}


# ---------------------------------------------------------------- resume, export, forget


async def test_an_interrupted_session_is_recovered_and_the_page_resumes_from_the_committed_cursor(settings):
    e = env(settings, [None, "The cat sat on the hat by the door.", "Mia saw a big", None], page=P1,
            learner="Ada")  # ends idle: a stop would complete the sentence by (iii)
    await run(e)
    store = e.store
    # what a process death mid-reading leaves (finalize never ran): libraries §7.1 measured it on Windows
    store.execute("UPDATE reading_sessions SET ended_at=NULL, summary=NULL")
    store.execute("UPDATE activities SET status='running', ended_at=NULL")
    store.execute("UPDATE cycles SET status='open', closed_reason=NULL, closed_at=NULL")
    store.execute("UPDATE miscues SET status='candidate', unsure_reason=NULL")
    e2 = env(settings, [None, "brown fox.", "/stop"], page=P1, learner="Ada")
    await run(e2)
    s1 = store.one("SELECT summary FROM reading_sessions WHERE id=1")
    assert loads(s1["summary"])["interrupted"] is True
    assert store.one("SELECT status FROM activities WHERE session_id=1")["status"] == "interrupted"
    assert _miscues(store)["small"][:2] == ("unsure", "interrupted")
    reads = store.all("SELECT * FROM page_reads ORDER BY id")
    assert [r["attempt"] for r in reads] == [1, 2]
    st = ReadingState.from_json(P1, loads(reads[1]["reading_state"]))
    assert st.statuses().split()[:15] == ["C"] * 9 + ["R"] * 4 + ["C"] * 2
    assert {1, 2} <= st.completed


async def test_export_and_forget_session_and_book(settings):
    e = env(settings, [None, "The cat sat on the mat by the door.", "/fix hat mat", "/stop"], page=P1,
            learner="Ada")
    sid = await run(e)
    store = e.store
    out = records.export_session(store, sid)
    assert out["book"] == "Fixture" and all("heard" not in m for m in out["miscues"])
    counts = summary(store, sid)["candidates"]
    records.forget_session(store, sid)
    for table in ("utterances", "observations", "practices", "miscues", "activities", "cycles"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    assert store.one("SELECT utterance_id FROM corrections")["utterance_id"] is None
    assert summary(store, sid)["candidates"] == counts
    assert pages.current_text(store, 1) == P1.replace("hat", "mat", 1)
    book = store.one("SELECT id FROM books")["id"]
    records.forget_book(store, book)
    for table in ("pages", "page_revisions", "corrections", "page_reads"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0
    assert store.one("SELECT archived_at FROM books")["archived_at"] is not None


async def test_a_whole_session_writes_as_its_learner(settings):
    store = Store(settings.db_path)
    from tests import seed

    seed.learner(store, "Ada")
    ben = seed.learner(store, "Ben")
    e = env(settings, [None, "The cat sat on the mat by the door.", None, "hat", "/stop"], page=P1, learner="Ben")
    sid = await run(e)
    assert store.one("SELECT learner_id FROM reading_sessions WHERE id=?", (sid,))["learner_id"] == ben
    assert {r["learner_id"] for r in store.all("SELECT rs.learner_id FROM utterances u JOIN reading_sessions rs "
                                               "ON rs.id = u.session_id")} == {ben}
    assert {r["learner_id"] for r in store.all("SELECT learner_id FROM retrieval_events")} <= {ben}


# ---------------------------------------------------------------- devices: microphone and lease


class LostAfterScript(ScriptedListener):
    def __init__(self, script, released: asyncio.Event) -> None:
        super().__init__(script, voice=True)
        self.released = released

    async def next_utterance(self, timeout_s):
        if not self.script:
            self.released.set()
            raise ListenerLost("microphone unplugged")
        return await super().next_utterance(timeout_s)


class GatedConsole(ScriptedListener):
    def __init__(self, script, gate: asyncio.Event) -> None:
        super().__init__(script)
        self.gate = gate

    async def next_utterance(self, timeout_s):
        await self.gate.wait()
        return await super().next_utterance(timeout_s)


async def test_the_session_continues_on_the_console_when_the_microphone_dies(settings):
    gate = asyncio.Event()
    voice = LostAfterScript([None, "The cat sat on the hat by the door."], gate)
    console = GatedConsole(["Mia saw a small brown fox.", "/stop"], gate)  # the reading goes on, no new offer
    e = env(settings, [], page=P1, learner="Ada", listener=voice, control_source=console)
    sid = await run(e)
    store = e.store
    acts = activities(store, sid)
    assert acts[0] == ("read_listen", "aborted_stale", False) and acts[1][0] == "read_listen"
    assert any("microphone" in t for t in e.face.texts)
    assert summary(store, sid)["end"] == "stop"
    reads = store.all("SELECT reading_state FROM page_reads")
    st = ReadingState.from_json(P1, loads(reads[0]["reading_state"]))
    assert {1, 2} <= st.completed  # one sentence by voice, one typed after the switch, the same page read
    assert [tuple(r) for r in store.all("SELECT key, state, reason FROM alert_outbox")] == \
        [("study-mic", "event", "mic_lost")]


async def test_the_session_stops_when_the_microphone_dies_and_there_is_no_console(settings):
    gate = asyncio.Event()
    e = env(settings, [], page=P1, learner="Ada", listener=LostAfterScript([None, "The cat sat on the hat."], gate))
    sid = await run(e)
    assert summary(e.store, sid)["end"] == "listener_lost_no_console"
    assert e.store.one("SELECT ended_at FROM reading_sessions")["ended_at"] is not None
    assert e.store.one("SELECT reason FROM alert_outbox")["reason"] == "mic_lost"


async def test_a_lost_lease_stops_the_session_and_nothing_plays_after_it(settings, tmp_path):
    settings = settings.model_copy(update={"lease_ttl_s": 0.3})

    class Blocking(ScriptedListener):
        async def next_utterance(self, timeout_s):
            if not self.script:
                settings.lease_path.write_text(json.dumps({"pid": os.getpid(), "token": "another-launch",
                                                           "expires": time.time() + 60}), encoding="utf-8")
                self.played_at_takeover = len(mouth.played)
                await asyncio.sleep(3600)
            return await super().next_utterance(timeout_s)

    mouth = FakeMouth()
    listener = Blocking([None, "The cat sat on the hat by the door."])
    face = RecordingFace()
    hub = Hub(faces={"c": face}, mouths={"m": mouth}, synthesizer=FakeSynth(tmp_path), policy="all",
              listeners={"console": listener})
    from leafi.study.harness import loop

    e = loop.Env(store=Store(settings.db_path), hub=hub, settings=settings, listener=listener, book_title="Fixture",
                 page_text=P1, page_number=1, learner="Ada")
    sid = await run(e)
    s = summary(e.store, sid)
    assert s["end"] == "lease_lost" and s["closing_line"] == "skipped"
    assert len(mouth.played) == listener.played_at_takeover  # nothing played after the takeover
    assert any("took over" in t for t in face.texts)  # said on the Faces only
    assert json.loads(settings.lease_path.read_text(encoding="utf-8"))["token"] == "another-launch"  # not unlinked
    assert [tuple(r) for r in e.store.all("SELECT key, state, reason FROM alert_outbox")] == \
        [("study-lease", "event", "lease_lost")]
