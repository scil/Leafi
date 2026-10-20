"""Plan S1 acceptance: the whole study loop in text mode with a scripted console, mock Brain and a fake
AnkiConnect. Real SQLite, real alignment, real corrections (never mocked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from leafi.core import lease
from leafi.core.hub import Hub
from leafi.core.storage import Store, loads
from leafi.services.brain import Intent
from leafi.services.brain.mock import MockBrain, default_reply
from leafi.study import anki, pages, records
from leafi.study.alignment import ReadingState
from leafi.study.session import StudySession
from tests.fakes import RecordingFace, ScriptedListener
from tests.fakes.anki import FakeAnki

PAGE = Path("tests/fixtures/pages/p1.txt").read_text(encoding="utf-8")

SCRIPT = [
    "good",                              # REVIEW_DUE: the answerCards response is lost
    "The cat sat on the mat",            # substitution: candidate at OCR'd "hat"
    "the book says mat not hat",         # correction utterance → revision 2, candidate invalidated
    "mat by the door.",                  # continue from the clamped cursor; sentence 1 completes
    "Mia saw",                           # hesitation split across two utterances ...
    "a small brown.",                    # ... typed line end completes; "fox" stays unread
    "It ran across the fill",            # substitution: candidate at "field"
    "ran across the field and hid.",     # reread of three words + self-correction
    "She smiled at the fox.",            # mid-sentence skip: deleted "clever" → candidate → PRACTICE
    "clever",                            #   retry matches → withdrawn(practice)
    "what does clever mean",             # EXPLAIN (word from the page)
    "Then the son went dawn slowly.",    # two substitutions → PRACTICE sun, down
    "son",                               #   sun retry 1 disagrees
    "son",                               #   sun retry 2 disagrees → unsure(disagreed)
    "/skip",                             #   down: /skip during practice → unsure(skipped)
    "a fox",                             # CHECK question 1 → correct
    "the sun went to bed",               # CHECK question 2 → incorrect (encounter, trigger=check)
    "/stop",
]


def questions(req):
    if req.intent is Intent.QUESTIONS:
        return {"questions": [
            {"question": "What did Mia see?", "answer": "She saw a fox.", "keywords": [["fox"]], "item_key": "fox"},
            {"question": "What did the sun do?", "answer": "It went down.", "keywords": [["down"]],
             "item_key": "went down"}], "action": "ask"}
    return default_reply(req)


@pytest.fixture
def run(settings, tmp_path):
    async def go(script=SCRIPT, brain=None, fake=None):
        store = Store(settings.db_path)
        face = RecordingFace()
        hub = Hub(faces={"console": face}, policy="none")
        fake = fake or FakeAnki()
        session = StudySession(store=store, hub=hub, settings=settings, brain=brain or MockBrain(questions),
                               anki_client=anki.AnkiClient(transport=fake.transport()),
                               listener=ScriptedListener(script))
        sid = await session.run(book_title="Fixture", page_text=PAGE, page_number=1)
        return store, sid, face, session, fake
    return go


def _miscues(store):
    return {r["expected"]: (r["status"], r["withdrawn_reason"] or r["unsure_reason"] or r["invalidated_reason"],
                            r["evidence"]) for r in store.all("SELECT * FROM miscues ORDER BY id")}


async def test_text_mode_scenario_end_to_end(run, settings):
    fake = FakeAnki()
    due = fake.add_due_card("blew", "moved air")
    fake.lose_next.update({"answerCards", "addNote"})
    store, sid, face, session, fake = await run(fake=fake)

    # ---- miscues and practice (ADR-0013 → Practice; text mode: evidence none, never confirmed)
    assert _miscues(store) == {
        "hat": ("invalidated", "page_text_corrected", "none"),
        "field": ("withdrawn", "self_corrected", "none"),
        "clever": ("withdrawn", "practice", "none"),
        "sun": ("unsure", "disagreed", "none"),
        "down": ("unsure", "skipped", "none"),
    }
    prac = [(r["expected"], r["attempt"], r["outcome"], r["evidence"]) for r in store.all(
        "SELECT m.expected, p.* FROM practices p JOIN miscues m ON m.id = p.miscue_id ORDER BY p.id")]
    assert prac == [("clever", 1, "matched", "none"), ("sun", 1, "disagreed", "none"),
                    ("sun", 2, "disagreed", "none"), ("down", 1, "skipped", "none")]

    # ---- observations of the first reading utterance
    u1 = store.one("SELECT id FROM utterances WHERE text='The cat sat on the mat'")["id"]
    obs = [(r["kind"], r["token_start"], r["heard_text"]) for r in
           store.all("SELECT * FROM observations WHERE utterance_id=? ORDER BY id", (u1,))]
    assert obs == [("matched", 0, "the"), ("matched", 1, "cat"), ("matched", 2, "sat"), ("matched", 3, "on"),
                   ("matched", 4, "the"), ("substituted", 5, "mat")]
    hes = store.one("SELECT id FROM utterances WHERE text='ran across the field and hid.'")["id"]
    assert [r["kind"] for r in store.all("SELECT kind FROM observations WHERE utterance_id=?", (hes,))] == [
        "matched"] * 6

    # ---- correction: revision chain, edit map, verified-span transform
    page_id = store.one("SELECT id FROM pages")["id"]
    chain = pages.chain(store, page_id)
    assert [(r.rev, r.source) for r in chain] == [(1, "manual"), (2, "correction")]
    start = PAGE.index("hat")
    assert chain[1].edit_map == [[start, start + 3, start, start + 3]]
    assert chain[1].spans_verified == [[0, len(PAGE)]]
    assert pages.current_text(store, page_id) == PAGE.replace("hat", "mat")
    corr = store.one("SELECT * FROM corrections")
    assert (corr["old_text"], corr["new_text"], corr["source"]) == ("hat", "mat", "text")
    assert corr["page_revision_id"] == chain[0].id and corr["utterance_id"] is not None

    # ---- persisted reading state (after every utterance; final here)
    pr = store.one("SELECT * FROM page_reads")
    st = ReadingState.from_json(pages.current_text(store, page_id), loads(pr["reading_state"]))
    assert pr["page_revision_id"] == chain[1].id
    assert st.completed == {1, 2, 3, 4, 5}
    assert st.statuses() == ("C C C C C C C C C  C C C C C R  C C C C S C C  C C C C S C  C C S C S C"
                             .replace("  ", " "))
    assert (st.pcur, st.ccur) == (34, 34)

    # ---- knowledge items + encounters (explain and check(incorrect)); learner text never a key
    items = {(r["kind"], r["key"], r["trigger"]) for r in store.all(
        "SELECT k.kind, k.key, e.trigger FROM encounters e JOIN knowledge_items k ON k.id = e.knowledge_item_id")}
    assert items == {("word", "clever", "explain"), ("fact", "went down", "check")}
    explained = store.one("SELECT explanation_en FROM encounters WHERE trigger='explain'")["explanation_en"]
    assert "clever" in explained

    # ---- Brain received page text only, never the learner's words
    reqs = session.brain.requests
    assert {r.intent for r in reqs} == {Intent.EXPLAIN_WORD, Intent.QUESTIONS}
    for r in reqs:
        assert "son" not in r.window.split() and "the sun went to bed" not in r.window

    # ---- Anki: lost addNote ack deduped by tag on the next sync; sent review answer never replayed
    ra = store.one("SELECT * FROM review_answers")
    assert (ra["card_id"], ra["ease"], ra["state"]) == (due, 3, "sent")
    assert store.one("SELECT COUNT(*) AS n FROM anki_outbox WHERE state='pending'")["n"] >= 1
    rep = await anki.sync_outbox(store, anki.AnkiClient(transport=fake.transport()))
    assert rep.deduped == 1
    assert fake.actions().count("answerCards") == 1
    assert sum(1 for n in fake.notes.values() if any(t.startswith("leafi-id::") for t in n["tags"])) == 2

    # ---- summary counts, wrap, lease
    s = store.one("SELECT * FROM reading_sessions WHERE id=?", (sid,))
    summ = loads(s["summary"])
    assert s["ended_at"] is not None and summ["stopped"] and not summ["interrupted"]
    assert {k: summ[k] for k in ("pages", "tokens_expected", "tokens_committed", "tokens_unread", "candidates",
                                 "withdrawn", "unsure", "invalidated", "practices", "items_learned")} == {
        "pages": 1, "tokens_expected": 34, "tokens_committed": 33, "tokens_unread": 1, "candidates": 5,
        "withdrawn": 2, "unsure": 2, "invalidated": 1, "practices": 4, "items_learned": 2}
    assert not lease.is_held(settings.lease_path)
    assert "Great session, teammate. See you next time!" in face.texts
    assert all("wrong" not in t.lower() for t in face.texts)


async def test_brain_unavailable_skips_explanation_and_check_without_difficulty(run):
    script = ["The cat sat on the hat by the door.", "what does door mean", "/stop"]
    store, sid, face, session, _ = await run(script=script, brain=MockBrain(unavailable=True))
    enc = store.one("SELECT * FROM encounters")
    assert enc["trigger"] == "explain" and enc["explanation_en"] is None
    assert store.all("SELECT * FROM difficulties") == []
    assert any("can't explain" in t for t in face.texts)


async def test_explain_target_not_on_the_page_never_leaves_the_lan(run):
    brain = MockBrain()
    script = ["The cat sat", "what does zephyrine mean", "/stop"]
    store, *_ = await run(script=script, brain=brain)
    (req,) = brain.requests
    assert req.intent is Intent.EXPLAIN_SENTENCE and req.target is None
    assert "zephyrine" not in req.window.lower()
    assert store.one("SELECT key FROM knowledge_items")["key"] == "The cat sat on the hat by the door."


async def test_stop_mid_sentence_completes_it_and_settles_open_candidates(run):
    script = ["The cat sat on the mat", "/stop"]
    store, sid, *_ = await run(script=script)
    assert _miscues(store) == {"hat": ("unsure", "skipped", "none")}
    pr = store.one("SELECT * FROM page_reads")
    assert pr["tokens_unread"] == 3  # "by the door" completed as read by the stop


async def test_control_precedence_wins_over_page_text_except_beyond_six_words(run, settings):
    """Review 1 #10 (reverses the 2026-10-20 page-text-precedence choice): "stop" on a page that begins with
    "Stop" stops; an utterance longer than the control grammar's 6 words is reading."""
    page = "Stop and look both ways. Then stop at home and rest."

    async def go(db, script):
        store = Store(settings.data_dir / db)
        hub = Hub(faces={"c": RecordingFace()}, policy="none")
        s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                         listener=ScriptedListener(script))
        await s.run(book_title="Signs", page_text=page, page_number=1)
        return store, [r["kind"] for r in store.all("SELECT kind FROM utterances ORDER BY id")]

    store, kinds = await go("a.db", ["Stop"])  # the expected first word is "Stop": still the command
    assert kinds == ["control"]
    assert loads(store.one("SELECT summary FROM reading_sessions")["summary"])["stopped"] is True
    store, kinds = await go("b.db", ["Stop and look both ways then stop", "/stop"])  # 7 words: reading
    assert kinds == ["reading", "control"]



async def test_export_and_forget_session(run, settings):
    store, sid, *_ = await run()
    out = records.export_session(store, sid)
    assert out["summary"]["candidates"] == 5 and out["book"] == "Fixture"
    assert all("heard" not in m for m in out["miscues"])
    records.forget_session(store, sid)
    for table in ("utterances", "observations", "practices", "miscues"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0
    assert store.one("SELECT utterance_id FROM corrections")["utterance_id"] is None
    assert loads(store.one("SELECT summary FROM reading_sessions")["summary"])["candidates"] == 5
    assert pages.current_text(store, 1) == PAGE.replace("hat", "mat")


async def test_forget_book_deletes_its_evidence_and_archives_it(run, settings):
    store, sid, *_ = await run()
    book_id = store.one("SELECT id FROM books")["id"]
    records.forget_book(store, book_id)
    for table in ("pages", "page_revisions", "corrections", "page_reads", "encounters"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0
    assert store.one("SELECT COUNT(*) AS n FROM lexicon WHERE book_id=?", (book_id,))["n"] == 0
    assert store.one("SELECT archived_at FROM books")["archived_at"] is not None
    assert store.one("SELECT COUNT(*) AS n FROM knowledge_items")["n"] == 2  # the learner's, not the book's
