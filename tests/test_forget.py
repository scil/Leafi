"""`forget --learner` and `forget --session|--book` over the local stores (ADR-0018 §1, ADR-0010 §9; plan M3.4), by
owning learner since ADR-0021 E9. Real SQLite, never mocked."""

from __future__ import annotations

import pytest

from leafi.core import learner_store
from leafi.core.storage import Store, now_iso
from leafi.study import corrections, knowledge, records
from tests import seed

TEXT = "The wind blew through the trees."


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


def _activity(store, session_id, *, assessment=None, cycle_id=None):
    return store.insert("activities", session_id=session_id, cycle_id=cycle_id, kind="read_listen", status="done",
                        started_at=now_iso(), assessment=assessment)


def _history(store, learner, book, page, rev):
    """A session with every kind of row the learner can own or reach (codex M3 #9: each table populated, so a
    deletion that is left out fails a test)."""
    s = seed.session(store, book, learner_id=learner)
    cycle = store.insert("cycles", session_id=s, status="closed", opened_at=now_iso())
    read = seed.page_read(store, s, page, rev)
    store.execute("UPDATE page_reads SET cycle_id=? WHERE id=?", (cycle, read))
    utt = seed.utterance(store, s, "the wind blue", page_read_id=read)
    obs = store.insert("observations", utterance_id=utt, kind="substituted", token_start=2, token_end=3,
                       heard_text="blue", created_at=now_iso())
    mid = seed.miscue(store, read, rev, TEXT, "blew", status="confirmed")
    store.execute("UPDATE miscues SET observation_id=?, cycle_id=? WHERE id=?", (obs, cycle, mid))
    store.insert("practices", miscue_id=mid, attempt=1, outcome="disagreed", evidence="acoustic",
                 created_at=now_iso())
    store.execute("UPDATE reading_sessions SET ended_at=? WHERE id=?", (now_iso(), s))
    item = knowledge.upsert_item(store, learner, "word", "blew")
    seed.card(store, item)
    knowledge.add_encounter(store, item, session_id=s, trigger="explain", explanation_en="moved air")
    learner_store.insert(store, "review_answers", learner, knowledge_item_id=item, card_id=1, ease=3,
                         state="acked", created_at=now_iso())
    learner_store.insert(store, "book_notes", learner, book_id=book, session_id=s, text="a fox story",
                         created_at=now_iso())
    act = _activity(store, s, cycle_id=cycle)
    note = learner_store.insert(store, "learner_notes", learner, session_id=s, text="likes foxes",
                                created_at=now_iso())
    store.insert("learner_note_citations", note_id=note, activity_id=act)
    learner_store.insert(store, "retrieval_events", learner, item_id=item, activity_id=act, at=now_iso(),
                         day="2026-10-23", outcome="success", evidence="typed")
    learner_store.insert(store, "consents", learner, purpose="remote_teacher", status="used", valid_from=now_iso(),
                         indicated_by="learner_voice", created_at=now_iso())
    store.insert("egress_log", destination="claude", purpose="decide", learner_id=learner, session_id=s,
                 payload_size=10, body_hmac="h", status="sent", created_at=now_iso(), updated_at=now_iso())
    store.insert("brain_calls", session_id=s, activity_id=act, purpose="decide", backend="mock", payload="p",
                 response="r", outcome="ok", created_at=now_iso())
    store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=? WHERE learner_id=?", (700 + learner, learner))
    learner_store.insert(store, "item_status_events", learner, item_id=item, at=now_iso(), day="2026-10-23",
                         event="ignore", source="brain", session_id=s, activity_id=act)
    learner_store.insert(store, "item_status_events", learner, item_id=item, at=now_iso(), day="2026-10-23",
                         event="card_state", source="anki", activity_id=act, card_id=1, ivl_days=3.0, lapses=0)
    learner_store.insert(store, "decision_records", learner, session_id=s, at=now_iso(), turn="t1",
                         record='{"leaves": []}')
    return s, utt


def test_forget_learner_removes_every_owned_store_and_keeps_others_copies(store, settings):
    """ADR-0021 E9: deletion by owning learner; copies of Ada's words in Ben's rows are kept (the stated cost)."""
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    book, page, rev = seed.book_page(store, TEXT)
    _, ada_utt = _history(store, ada, book, page, rev)
    ben_session, _ = _history(store, ben, book, page, rev)
    _activity(store, ben_session, assessment="Ada helped")  # Ben's record quoting Ada
    store.insert("brain_calls", session_id=ben_session, purpose="judge", backend="mock", payload="Ada said x",
                 outcome="ok", created_at=now_iso())
    span = corrections.locate(TEXT, "trees", near=0)
    corrections.apply_correction(store, page_id=page, revision_id=rev, char_start=span[0], char_end=span[1],
                                 new_text="tree", source="voice", learner_id=ada, utterance_id=ada_utt)
    (settings.data_dir / "learners" / str(ada)).mkdir(parents=True)
    (settings.data_dir / "learners" / str(ada) / "voice.npy").write_bytes(b"x")

    rep = records.forget_learner(store, ada, settings.data_dir)

    assert learner_store.get(store, ada) is None
    for table in ("reading_sessions", "knowledge_items", "encounters", "difficulties", "anki_outbox",
                  "review_answers", "learner_notes", "book_notes", "retrieval_events", "consents", "egress_log",
                  "item_status_events", "decision_records"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table} WHERE learner_id=?", (ada,))["n"] == 0, table
    for table in ("item_status_events", "decision_records"):  # Ben's own stay
        assert store.one(f"SELECT COUNT(*) AS n FROM {table} WHERE learner_id=?", (ben,))["n"] >= 1, table
    # Ben keeps everything of his own, including the copies that quote Ada
    assert store.one("SELECT COUNT(*) AS n FROM activities WHERE assessment='Ada helped'")["n"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM brain_calls WHERE session_id=?", (ben_session,))["n"] == 2
    assert store.one("SELECT COUNT(*) AS n FROM knowledge_items WHERE learner_id=?", (ben,))["n"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM reading_sessions WHERE learner_id=?", (ben,))["n"] == 1
    # the correction stays as book text, unlinked; the name is a household term now
    c = store.one("SELECT * FROM corrections")
    assert (c["source_learner_id"], c["utterance_id"], c["forgotten"]) == (None, None, 1)
    assert store.one("SELECT term, kind FROM household_terms")[:] == ("Ada", "name")
    assert not (settings.data_dir / "learners" / str(ada)).exists()
    assert rep.anki_notes == [700 + ada] and rep.deck == "Leafi Ada #1" and rep.sessions == 1
    assert store.one("PRAGMA foreign_key_check") is None
    for table in ("cycles", "observations", "practices", "miscues", "page_reads", "book_notes", "review_answers"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 1, table


def test_every_protected_name_is_kept_once_and_existing_terms_stay(store, settings):
    """ADR-0021 E9 (U7, V6): display name and alias go into `household_terms`, deduplicated up to case and
    idempotent; an existing term (a shared school, a hand-added name) keeps its row and kind."""
    from leafi.privacy import pseudonym
    from leafi.privacy import settings as privacy

    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    store.execute("UPDATE learners SET alias='ADA' WHERE id=?", (ada,))  # the same name up to case
    mia = seed.learner(store, "Mia")
    store.execute("UPDATE learners SET alias='Mimi' WHERE id=?", (mia,))
    store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('mimi', 'other', 't')")
    privacy.set_school(store, mia, "Oakwood")
    privacy.set_school(store, ben, "Oakwood")  # shared with a sibling
    records.forget_learner(store, ada, settings.data_dir)
    records.forget_learner(store, mia, settings.data_dir)
    terms = {r["term"]: (r["kind"], r["former_learner_id"]) for r in store.all("SELECT * FROM household_terms")}
    assert terms["Ada"] == ("name", ada) and "ADA" not in terms
    assert terms["Mia"] == ("name", mia) and terms["mimi"] == ("other", None)  # the existing term stays as it was
    assert terms["Oakwood"][0] == "school"
    p = pseudonym.build(store.conn, b"k" * 32)
    from leafi.privacy.pseudonym import Mapping

    out = p.apply("Ben asked Ada and Mimi at Oakwood", Mapping())
    assert "Ada" not in out and "Mimi" not in out and "Oakwood" not in out


def test_notes_follow_their_session_and_their_citations(store, settings):
    """ADR-0021 E9 (V7): a note attached to Ada's session goes whoever owns it; Ben's note in his own session
    cited by both keeps its row and loses Ada's citation; Ben's note cited only by Ada's activities goes."""
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    s_ada, s_ben = seed.session(store, None, learner_id=ada), seed.session(store, None, learner_id=ben)
    for s in (s_ada, s_ben):
        store.execute("UPDATE reading_sessions SET ended_at=? WHERE id=?", (now_iso(), s))
    a_act, b_act = _activity(store, s_ada), _activity(store, s_ben)
    in_ada = learner_store.insert(store, "learner_notes", ben, session_id=s_ada, text="x", created_at=now_iso())
    both = learner_store.insert(store, "learner_notes", ben, session_id=s_ben, text="y", created_at=now_iso())
    only_ada = learner_store.insert(store, "learner_notes", ben, session_id=None, text="z", created_at=now_iso())
    for note, act in ((both, a_act), (both, b_act), (only_ada, a_act), (in_ada, b_act)):
        store.insert("learner_note_citations", note_id=note, activity_id=act)
    records.forget_learner(store, ada, settings.data_dir)
    left = {r["id"] for r in store.all("SELECT id FROM learner_notes")}
    assert left == {both}
    assert [r["activity_id"] for r in store.all("SELECT activity_id FROM learner_note_citations")] == [b_act]


def test_a_folder_that_cannot_be_deleted_keeps_the_learner_marked(store, settings, monkeypatch):
    ada = seed.learner(store, "Ada")
    (settings.data_dir / "learners" / str(ada)).mkdir(parents=True)

    def denied(path):
        raise PermissionError("held open")

    monkeypatch.setattr(records.shutil, "rmtree", denied)
    with pytest.raises(PermissionError):
        records.forget_learner(store, ada, settings.data_dir)
    assert learner_store.get(store, ada)["forgetting"] == 1
    monkeypatch.undo()
    records.forget_learner(store, ada, settings.data_dir)
    assert learner_store.get(store, ada) is None


def test_another_learners_egress_row_naming_the_consent_does_not_block(store, settings):
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    consent = learner_store.insert(store, "consents", ada, purpose="remote_teacher", status="used",
                                   valid_from=now_iso(), indicated_by="learner_voice", created_at=now_iso())
    row = store.insert("egress_log", destination="claude", purpose="media", learner_id=ben, consent_id=consent,
                       payload_size=1, body_hmac="h", status="sent", created_at=now_iso(), updated_at=now_iso())
    records.forget_learner(store, ada, settings.data_dir)
    assert store.one("SELECT consent_id FROM egress_log WHERE id=?", (row,))["consent_id"] is None


def test_cards_to_remove_survive_a_forget_stopped_between_batches(store, settings, monkeypatch):
    ada = seed.learner(store, "Ada")
    book, page, rev = seed.book_page(store, TEXT)
    _history(store, ada, book, page, rev)
    monkeypatch.setattr(records, "sweep_tts_cache", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):  # the outbox rows are already deleted at this point
        records.forget_learner(store, ada, settings.data_dir)
    assert store.one("SELECT COUNT(*) AS n FROM anki_outbox")["n"] == 0
    assert learner_store.get(store, ada)["forgetting"] == 1
    assert learner_store.enrolled(store) == []  # never offered while marked
    monkeypatch.undo()
    assert records.forget_learner(store, ada, settings.data_dir).anki_notes == [700 + ada]
    assert learner_store.get(store, ada) is None


def test_forget_learner_is_refused_while_a_live_process_has_a_session_whose_egress_is_not_over(store, settings):
    """M5 design D5: a session is busy until `post_done_at` (after delivery), not only until `ended_at`."""
    from leafi.privacy.egress import owner

    ada = seed.learner(store, "Ada")
    sid = seed.session(store, None, learner_id=ada)
    store.execute("UPDATE reading_sessions SET ended_at=?, owner=? WHERE id=?", (now_iso(), owner(), sid))
    with pytest.raises(records.LearnerBusy):  # ended, still delivering in this (live) process
        records.forget_learner(store, ada, settings.data_dir)
    assert learner_store.get(store, ada)["forgetting"] == 0


def test_a_dead_processes_unfinished_session_does_not_block_forget(store, settings):
    ada = seed.learner(store, "Ada")
    sid = seed.session(store, None, learner_id=ada)
    store.execute("UPDATE reading_sessions SET ended_at=?, owner='999999:1' WHERE id=?", (now_iso(), sid))
    records.forget_learner(store, ada, settings.data_dir)
    assert learner_store.get(store, ada) is None


def test_the_fence_refuses_writes_owned_by_a_learner_being_forgotten_and_lets_others_through(store, settings):
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ada,))  # what the first step commits
    with pytest.raises(learner_store.LearnerUnavailable):
        learner_store.insert(store, "learner_notes", ada, text="x", created_at=now_iso())
    learner_store.insert(store, "learner_notes", ben, text="Ada likes foxes", created_at=now_iso())  # Ben's own
    records.forget_learner(store, ada, settings.data_dir)
    with pytest.raises(learner_store.LearnerUnavailable):  # after: the row is gone
        learner_store.insert(store, "learner_notes", ada, text="x", created_at=now_iso())


def test_the_final_sweep_removes_a_row_written_between_batches(store, settings, monkeypatch):
    """U11: a writer that skipped the fence lands after the batches; the final by-owner sweep deletes it, so the
    learner row's delete does not fail on the foreign key."""
    ada = seed.learner(store, "Ada")
    real = records.sweep_tts_cache
    calls = []

    def slip_in(st, cache_dir):
        calls.append(1)
        if len(calls) == 1:
            st.insert("learner_notes", learner_id=ada, text="x", created_at=now_iso())
        return real(st, cache_dir)

    monkeypatch.setattr(records, "sweep_tts_cache", slip_in)
    records.forget_learner(store, ada, settings.data_dir)
    assert store.one("SELECT COUNT(*) AS n FROM learner_notes")["n"] == 0 and learner_store.get(store, ada) is None


def test_the_tts_cache_folder_of_the_learner_and_of_stale_guests_goes(store, settings, tmp_path):
    """ADR-0021 E9: `<cache>/tts/learners/<id>/` of the forgotten learner and of a guest whose sessions all ended
    go; another learner's folder, a guest with an open session, `shared/` and the habit track's files stay."""
    from leafi.study.harness import guests

    cache = tmp_path / "cache"
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    stale_guest, live_guest = guests.new_guest(store), guests.new_guest(store)
    for g, done in ((stale_guest, now_iso()), (live_guest, None)):
        sid = store.insert("reading_sessions", learner_id=g, started_at=now_iso(), mode="text")
        store.execute("UPDATE reading_sessions SET post_done_at=? WHERE id=?", (done, sid))
    for lid in (ada, ben, stale_guest, live_guest, 9999):
        (cache / "tts" / "learners" / str(lid)).mkdir(parents=True)
        (cache / "tts" / "learners" / str(lid) / "k.wav").write_bytes(b"x")
    (cache / "tts" / "shared").mkdir()
    (cache / "tts" / "habit.mp3").write_bytes(b"x")
    rep = records.forget_learner(store, ada, settings.data_dir, cache_dir=cache)
    kept = sorted(p.name for p in (cache / "tts" / "learners").iterdir())
    assert kept == sorted([str(ben), str(live_guest)]) and rep.cache_left == []
    assert (cache / "tts" / "shared").is_dir() and (cache / "tts" / "habit.mp3").exists()


def _failed_finalisation(store, learner):
    """`run_session` set `post_done_at` but could not set `ended_at` (a busy store at finalize); no activity is
    still running. Recovery reaches it through `ended_at IS NULL` (ADR-0021 E9, W5, X2)."""
    book, page, rev = seed.book_page(store, TEXT)
    s = seed.session(store, book, learner_id=learner)
    read = seed.page_read(store, s, page, rev)
    mid = seed.miscue(store, read, rev, TEXT, "blew")
    store.insert("cycles", session_id=s, status="open", opened_at=now_iso())
    store.execute("UPDATE reading_sessions SET post_done_at=? WHERE id=?", (now_iso(), s))
    return s, mid


def test_recovery_closes_a_failed_finalisation_of_a_live_learner(store):
    from leafi.study.harness import rows

    ben = seed.learner(store, "Ben")
    s, mid = _failed_finalisation(store, ben)
    assert rows.recover(store) == [s]
    assert store.one("SELECT ended_at FROM reading_sessions WHERE id=?", (s,))["ended_at"] is not None
    assert store.one("SELECT status FROM cycles WHERE session_id=?", (s,))["status"] == "closed"
    assert seed.status_of(store, mid)[0] == "unsure"


def test_recovery_skips_a_session_whose_learner_is_being_forgotten_without_a_write(store):
    from leafi.study.harness import rows

    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    s, mid = _failed_finalisation(store, ada)
    healthy, _ = _failed_finalisation(store, ben)
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ada,))  # between two `forget` batches
    rows.recover(store)  # never raises, never aborts startup
    assert store.one("SELECT ended_at FROM reading_sessions WHERE id=?", (s,))["ended_at"] is None
    assert store.one("SELECT status FROM cycles WHERE session_id=?", (s,))["status"] == "open"
    assert seed.status_of(store, mid)[0] == "candidate"
    assert store.one("SELECT ended_at FROM reading_sessions WHERE id=?", (healthy,))["ended_at"] is not None


def test_forget_session_reaches_the_new_tables(store, settings):
    ada = seed.learner(store, "Ada")
    book, page, rev = seed.book_page(store, TEXT)
    s, _ = _history(store, ada, book, page, rev)
    other, _ = _history(store, ada, book, page, rev)
    records.forget_session(store, s)
    for table in ("activities", "brain_calls", "egress_log", "cycles"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table} WHERE session_id=?", (s,))["n"] == 0, table
        assert store.one(f"SELECT COUNT(*) AS n FROM {table} WHERE session_id=?", (other,))["n"] == 1, table
    assert store.one("SELECT cycle_id FROM page_reads WHERE session_id=?", (s,))["cycle_id"] is None
    assert store.one("SELECT COUNT(*) AS n FROM learner_notes WHERE session_id=?", (s,))["n"] == 0
    assert store.one("SELECT COUNT(*) AS n FROM learner_notes WHERE session_id=?", (other,))["n"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM retrieval_events")["n"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM reading_sessions WHERE id=?", (s,))["n"] == 1  # counts kept


def test_forget_book_deletes_its_book_notes(store, settings):
    ada = seed.learner(store, "Ada")
    book, page, rev = seed.book_page(store, TEXT)
    learner_store.insert(store, "book_notes", ada, book_id=book, text="a fox story", created_at=now_iso())
    records.forget_book(store, book)
    assert store.one("SELECT COUNT(*) AS n FROM book_notes")["n"] == 0


def test_forget_learner_command_confirms_first_and_says_what_is_kept(settings, monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    with Store(settings.db_path) as store:
        ada = seed.learner(store, "Ada")
    assert cli.main(["forget", "--learner", str(ada)]) == 1
    out = capsys.readouterr().out
    assert "Run again with --yes" in out and records.KEPT_NOTICE in out
    with Store(settings.db_path) as store:
        assert learner_store.get(store, ada) is not None
    assert cli.main(["forget", "--learner", str(ada), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "forgot learner" in out and "check Anki" in out
    with Store(settings.db_path) as store:
        assert learner_store.get(store, ada) is None


def test_discarding_a_guest_removes_its_status_events_and_decision_records(store):
    """D22 (round 5 #8): a guest that wrote an `ignore` and a `card_ack` is discarded with foreign keys on."""
    from leafi.study import item_status
    from leafi.study.harness import guests

    guest = guests.new_guest(store)
    s = seed.session(store, None, learner_id=guest)
    item = knowledge.upsert_item(store, guest, "word", "blew")
    item_status.record(store, guest, item, "ignore", "learner", session_id=s)
    item_status.record(store, guest, item, "card_ack", "anki", card_id=9)
    learner_store.insert(store, "decision_records", guest, session_id=s, at=now_iso(), turn="t1", record="{}")
    assert guests.discard(store, guest) == 1
    for table in ("item_status_events", "decision_records", "knowledge_items"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    assert store.one("PRAGMA foreign_key_check") is None
