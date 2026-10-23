"""Controls by state (ADR-0013 → Control precedence; flows/reading-session.md global transitions)."""

from __future__ import annotations

from leafi.core.hub import Hub
from leafi.core.storage import Store, loads
from leafi.services.brain.mock import MockBrain
from leafi.study import anki
from leafi.study.session import StudySession
from tests.fakes import RecordingFace, ScriptedListener
from tests.fakes.anki import FakeAnki

PAGE = "The dog ran far. The cat sat."


async def _run(settings, script, brain=None, fake=None):
    store = Store(settings.db_path)
    face = RecordingFace()
    s = StudySession(store=store, hub=Hub(faces={"f": face}, policy="none"), settings=settings,
                     brain=brain or MockBrain(), listener=ScriptedListener(script),
                     anki_client=anki.AnkiClient(transport=fake.transport()) if fake else None)
    sid = await s.run(book_title="Controls", page_text=PAGE, page_number=1)
    return store, face, s, sid


def _miscues(store):
    return {r["expected"]: (r["status"], r["unsure_reason"]) for r in store.all("SELECT * FROM miscues")}


async def test_skip_in_read_completes_the_sentence_and_moves_on(settings):
    store, face, s, _ = await _run(settings, ["The dog red", "/skip", "/stop"])
    assert _miscues(store) == {"ran": ("unsure", "skipped")}
    assert store.one("SELECT tokens_unread FROM page_reads")["tokens_unread"] == 4  # "far" + "The cat sat"


async def test_page_turn_settles_open_candidates_and_finds_the_new_page(settings, tmp_path):
    page2 = tmp_path / "p2.txt"
    page2.write_text("Second page here.", encoding="utf-8")
    store, face, s, _ = await _run(settings, ["The dog red", f"/page 2 --text {page2}", "Second page here.", "/stop"])
    assert _miscues(store) == {"ran": ("unsure", "skipped")}
    reads = store.all("SELECT p.printed_number, pr.ended_at FROM page_reads pr JOIN pages p ON p.id = pr.page_id "
                      "ORDER BY pr.id")
    assert [r["printed_number"] for r in reads] == [1, 2]
    assert all(r["ended_at"] for r in reads)


async def test_spoken_next_page_asks_for_the_next_page(settings):
    store, face, s, _ = await _run(settings, ["The dog", "next page", "/stop"])
    assert any("/page N --text" in t for t in face.texts)
    assert "FIND_PAGE" in s.flags.transitions[1:]


async def test_stop_in_check_wraps(settings):
    store, face, s, sid = await _run(settings, ["The dog ran far. The cat sat.", "/stop"])
    assert s.flags.transitions[-2:] == ["CHECK", "WRAP"]
    assert loads(store.one("SELECT summary FROM reading_sessions")["summary"])["stopped"] is True


async def test_skip_in_check_leaves_with_no_record(settings):
    store, face, s, _ = await _run(settings, ["The dog ran far. The cat sat.", "/skip", "/stop"])
    assert store.all("SELECT * FROM encounters") == []
    assert store.all("SELECT * FROM utterances WHERE kind='answer'") == []


async def test_skip_in_review_due_leaves_with_no_record(settings):
    fake = FakeAnki()
    fake.add_due_card("blew")
    store, face, s, _ = await _run(settings, ["/skip", "/stop"], fake=fake)
    assert store.all("SELECT * FROM review_answers") == []
    assert "answerCards" not in fake.actions()


async def test_a_control_that_does_not_apply_is_a_spoken_no_op(settings):
    store, face, s, _ = await _run(settings, ["/good", "/stop"])
    assert "That doesn't do anything right now." in face.texts


async def test_back_from_check_returns_to_read(settings):
    store, face, s, _ = await _run(settings, ["The dog ran far. The cat sat.", "/back", "The cat sat.", "/stop"],
                                   brain=MockBrain(unavailable=True))
    assert s.flags.transitions.count("CHECK") == 2
    assert s.flags.transitions.count("READ") == 2


def _first_obs_token(store, text):
    rows = store.all("SELECT id FROM utterances WHERE text=? AND kind='reading' ORDER BY id", (text,))
    return store.one("SELECT MIN(token_start) AS t FROM observations WHERE utterance_id=?", (rows[-1]["id"],))["t"]


async def test_back_right_after_completion_reopens_the_sentence_just_read(settings):
    script = ["The dog ran far.", "/back", "The dog ran far.", "The cat sat.", "/stop"]
    store, face, s, _ = await _run(settings, script, brain=MockBrain(unavailable=True))
    assert store.one("SELECT COUNT(*) AS n FROM utterances WHERE text='The dog ran far.'")["n"] == 2
    assert _first_obs_token(store, "The dog ran far.") == 0  # re-read aligned against sentence 1 again
    assert store.one("SELECT tokens_unread FROM page_reads")["tokens_unread"] == 0


async def test_back_during_practice_reopens_the_practised_sentence(settings):
    script = ["The dog red far.", "/back", "The dog ran far.", "The cat sat.", "/stop"]
    store, face, s, _ = await _run(settings, script, brain=MockBrain(unavailable=True))
    assert _miscues(store) == {"ran": ("unsure", "skipped")}  # open candidate of the aborted practice
    assert _first_obs_token(store, "The dog ran far.") == 0
    assert store.one("SELECT tokens_unread FROM page_reads")["tokens_unread"] == 0


async def test_controls_in_check_are_dispatched_not_graded(settings):
    """Review 1 #5: an inapplicable control at a CHECK question is a no-op; the question still awaits an answer."""
    store, face, s, _ = await _run(settings, ["The dog ran far. The cat sat.", "/explain fox", "/good", "a fox",
                                              "/stop"])
    answers = [r["text"] for r in store.all("SELECT text FROM utterances WHERE kind='answer'")]
    assert answers == ["a fox"]
    assert face.texts.count("That doesn't do anything right now.") == 2


async def test_an_empty_typed_line_is_a_line_end_never_an_alignment(settings):
    """Review 1 #13: Enter on an empty line is a typed line end (ADR-0013 completion (ii)), never alignment.
    v2: it does not complete the sentence while a content word ("far") is still unattempted."""
    store, face, s, _ = await _run(settings, ["The dog ran", "", "/stop"])
    assert store.one("SELECT COUNT(*) AS n FROM utterances WHERE text=''")["n"] == 0
    assert "CHECK" not in s.flags.transitions
    assert store.one("SELECT tokens_unread FROM page_reads")["tokens_unread"] == 1  # "far", by the stop


async def test_empty_lines_never_trigger_reposition(settings):
    store, face, s, _ = await _run(settings, ["The", "", "", "/stop"])
    assert not any("first few words" in t for t in face.texts)
    assert store.all("SELECT * FROM observations WHERE utterance_id IN (SELECT id FROM utterances WHERE text='')") == []


async def test_page_command_with_text_works_the_same_in_practice_and_check(settings, tmp_path):
    """Review 1 #14."""
    page2 = tmp_path / "p2.txt"
    page2.write_text("Second page here.", encoding="utf-8")
    for db, script in (("practice.db", ["The dog red far.", f"/page 2 --text {page2}", "/stop"]),
                       ("check.db", ["The dog ran far. The cat sat.", f"/page 2 --text {page2}", "/stop"])):
        settings.data_dir = tmp_path / db
        store, face, s, _ = await _run(settings, script)
        reads = store.all("SELECT p.printed_number, pr.ended_at, rev.text FROM page_reads pr JOIN pages p ON "
                          "p.id = pr.page_id JOIN page_revisions rev ON rev.id = pr.page_revision_id ORDER BY pr.id")
        assert [(r["printed_number"], r["text"]) for r in reads] == [(1, PAGE), (2, "Second page here.")], db
        assert all(r["ended_at"] for r in reads), db


async def test_a_very_long_sentence_never_crashes_enrichment(settings):
    """Review 1 #15: the Brain window is bounded to 900 characters; request errors fall back."""
    long_page = " ".join(["elephant"] * 110) + "."
    store = Store(settings.db_path)
    brain = MockBrain()
    s = StudySession(store=store, hub=Hub(faces={"f": RecordingFace()}, policy="none"), settings=settings,
                     brain=brain, listener=ScriptedListener([long_page, "what does elephant mean", "/stop"]))
    await s.run(book_title="Long", page_text=long_page, page_number=1)
    assert brain.requests and all(len(r.window) <= 900 for r in brain.requests)
