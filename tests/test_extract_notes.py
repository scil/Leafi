"""What the Brain may write (ADR-0017 §7.1; M7 design D18): a decision's records, the post-session learner notes,
and the notes the observation's memory shows. Real Store and Inputs, a mock Brain; nothing speaks."""

from __future__ import annotations

from leafi.core import learner_store
from leafi.core.storage import now_iso
from leafi.services.brain.mock import MockModel
from leafi.study import knowledge
from leafi.study.brain import call as bc
from leafi.study.brain import notes, schemas
from leafi.study.harness import guests
from tests import seed
from tests.harness_world import make_world, run

LINES = ["The fox ran home.", "It was late and dark."]


def _brain(w, reply):
    model = MockModel({"generate": reply})
    w.s.brain = bc.Brain({"fast": [], "standard": [(model, "mock-model")], "deep": []},
                         locality=lambda backend, m: "local")
    return model


async def _session(settings):
    w = make_world(settings, settings, LINES)
    _, _, aid = await run(w, "read_listen", {"page": "current", "range": "rest"})
    return w, aid


# ---------------------------------------------------------------- apply_records


async def test_each_record_is_validated_alone_and_the_valid_ones_are_written(settings):
    w, aid = await _session(settings)
    fox = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    ids = {f"a{aid}": ("activity", aid), f"i{fox}": ("item", fox), "a999": ("activity", 999)}
    recs = [schemas.Assessment(kind="assessment", activity_id=f"a{aid}", text="Read smoothly, paused at dark."),
            schemas.Assessment(kind="assessment", activity_id="a999", text="not this session's"),
            schemas.Assessment(kind="assessment", activity_id="a12345", text="never rendered"),
            schemas.ItemIgnored(kind="item_ignored", item_id=f"i{fox}"),
            schemas.ItemIgnored(kind="item_ignored", item_id="i404"),
            schemas.BookNote(kind="book_note", topic="a fox", characters="the fox", summary="A fox runs home."),
            schemas.BookNote(kind="book_note", topic="", characters="", summary="A stupid story.")]
    counts = notes.apply_records(w.s, w, recs, ids, w.s.epoch())
    assert counts == {"assessment": 1, "item_ignored": 1, "book_note": 1, "dropped": 4}
    assert w.store.one("SELECT assessment FROM activities WHERE id=?", (aid,))["assessment"].startswith("Read")
    assert w.store.one("SELECT status FROM knowledge_items WHERE id=?", (fox,))["status"] == "ignored"
    ev = w.store.one("SELECT event, source, session_id FROM item_status_events")
    assert tuple(ev) == ("ignore", "brain", w.s.session_id)
    assert w.store.one("SELECT text FROM book_notes")["text"] == "A fox runs home."


async def test_records_made_under_an_older_epoch_are_all_dropped(settings):
    w, aid = await _session(settings)
    epoch = w.s.epoch()
    w.s.latch.epoch.bump()  # a page turned while the Brain decided
    recs = [schemas.Assessment(kind="assessment", activity_id=f"a{aid}", text="fine")]
    assert notes.apply_records(w.s, w, recs, {f"a{aid}": ("activity", aid)}, epoch)["dropped"] == 1
    assert w.store.one("SELECT assessment FROM activities WHERE id=?", (aid,))["assessment"] is None


# ---------------------------------------------------------------- extract_notes


def _notes_reply(aid):
    return {"notes": [{"text": "Slows down at long words.", "activity_ids": [f"a{aid}"]},
                      {"text": "Cites nothing it was shown.", "activity_ids": ["a99999"]},
                      {"text": "Reads the second line faster.", "activity_ids": [f"a{aid}", f"a{aid}"]}]}


async def test_notes_cite_rendered_activities_and_an_unrendered_citation_drops_the_note(settings):
    w, aid = await _session(settings)
    model = _brain(w, lambda req: _notes_reply(aid))
    summ = {}
    await notes.extract_notes(w.s, w, None, summ, deadline_s=5)
    assert summ["notes"] == 2
    rows = w.store.all("SELECT n.text, c.activity_id FROM learner_notes n JOIN learner_note_citations c ON "
                       "c.note_id = n.id ORDER BY n.id")
    assert [tuple(r) for r in rows] == [("Slows down at long words.", aid), ("Reads the second line faster.", aid)]
    assert model.requests[0].purpose == "generate"
    assert [s.name for s in model.requests[0].turns[0].sections] == ["learner_context", "activities"]
    assert w.store.one("SELECT COUNT(*) AS n FROM brain_calls WHERE purpose='generate'")["n"] == 1


async def test_notes_are_written_after_stop_and_with_the_session_budget_spent(settings):
    w, aid = await _session(settings)
    _brain(w, lambda req: _notes_reply(aid))
    w.s.latch.terminal = "stop"
    w.s.ledger.brain_spent = w.s.ledger.limits.brain_calls  # the session's ledger is not the post-session allowance
    summ = {}
    await notes.extract_notes(w.s, w, None, summ, deadline_s=5)
    assert summ["notes"] == 2


async def test_the_post_session_allowance_and_a_missing_brain(settings):
    from leafi.study.harness import settings as learner_settings

    w, aid = await _session(settings)
    summ = {}
    await notes.extract_notes(w.s, w, None, summ, deadline_s=5)
    assert summ["notes"] == "skipped"  # no Brain
    model = _brain(w, lambda req: _notes_reply(aid))
    learner_settings.save(w.store, w.s.learner_id, {"limits.extract_calls": 0})
    w.s.settings = learner_settings.load(w.store, w.s.learner_id)
    await notes.extract_notes(w.s, w, None, summ, deadline_s=5)
    assert summ["notes"] == "unavailable" and model.requests == []


async def test_guests_get_no_notes(settings):
    w, aid = await _session(settings)
    model = _brain(w, lambda req: _notes_reply(aid))
    guest = guests.new_guest(w.store)
    w.store.execute("UPDATE reading_sessions SET learner_id=? WHERE id=?", (guest, w.s.session_id))
    w.s.learner_id = guest
    summ = {}
    await notes.extract_notes(w.s, w, None, summ, deadline_s=5)
    assert summ["notes"] == "skipped" and model.requests == []


# ---------------------------------------------------------------- notes leave memory after 10 sessions


def _note(store, learner, session, text, activity):
    note = learner_store.insert(store, "learner_notes", learner, session_id=session, text=text, created_at=now_iso())
    store.insert("learner_note_citations", note_id=note, activity_id=activity)
    return note


def _activity(store, session):
    return store.insert("activities", session_id=session, kind="read_listen", status="completed",
                        started_at=now_iso())


def test_a_note_leaves_memory_once_its_activities_are_ten_sessions_old_unless_a_newer_note_cites_them(settings):
    from leafi.core.storage import Store

    store = Store(settings.db_path)
    learner = seed.learner(store)
    first = seed.session(store, None, learner_id=learner)
    old_act = _activity(store, first)
    old = _note(store, learner, first, "Likes animal stories.", old_act)
    for _ in range(9):
        seed.session(store, None, learner_id=learner)
    assert [n for n, _ in notes.current_notes(store, learner)] == [old]  # the 10th most recent session
    later = seed.session(store, None, learner_id=learner)
    assert notes.current_notes(store, learner) == []  # eleven sessions: out of memory
    newer = _note(store, learner, later, "Still likes animal stories.", old_act)
    # the old note comes back: a newer note cites its activity; the newer one cites only that old activity and no
    # note is newer than it, so it is out by the same rule
    assert [n for n, _ in notes.current_notes(store, learner)] == [old]
    _note(store, learner, later, "Reads faster now.", _activity(store, later))
    assert newer not in [n for n, _ in notes.current_notes(store, learner)]
    other = seed.learner(store, "Ben")
    assert notes.current_notes(store, other) == []
