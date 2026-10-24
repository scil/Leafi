"""`forget --learner` and `forget --session|--book` over the local stores (ADR-0018 §1, ADR-0010 §9; plan M3.4).
Real SQLite, never mocked. The TTS-cache sidecars (M5) and decision records (M7) are not built yet."""

from __future__ import annotations

import pytest

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, now_iso
from leafi.study import corrections, knowledge, records
from tests import seed

TEXT = "The wind blew through the trees."


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


def _activity(store, session_id, *, assessment=None, sources=(), cycle_id=None):
    cls, src = learner_store.prov("derived_from_learner" if sources else "system", sources)
    return store.insert("activities", session_id=session_id, cycle_id=cycle_id, kind="read_listen", status="done",
                        started_at=now_iso(), outcome_provenance_class="system", outcome_source_learners="[]",
                        assessment=assessment, assessment_provenance_class=cls, assessment_source_learners=src)


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
                         provenance_class="derived_from_learner", source_learners=dumps([learner]),
                         created_at=now_iso())
    act = _activity(store, s, cycle_id=cycle)
    note = learner_store.insert(store, "learner_notes", learner, sources=[learner], session_id=s, text="likes foxes",
                                provenance_class="derived_from_learner", source_learners=dumps([learner]),
                                created_at=now_iso())
    store.insert("learner_note_citations", note_id=note, activity_id=act)
    learner_store.insert(store, "retrieval_events", learner, item_id=item, activity_id=act, at=now_iso(),
                         day="2026-10-23", outcome="success", evidence="typed")
    learner_store.insert(store, "consents", learner, purpose="cloud_text", status="granted", valid_from=now_iso(),
                         indicated_by="household_setting", created_at=now_iso())
    store.insert("egress_log", destination="claude", purpose="decide", learner_id=learner, session_id=s,
                 payload_size=10, body_hmac="h", status="sent", created_at=now_iso(), updated_at=now_iso())
    store.insert("brain_calls", session_id=s, activity_id=act, purpose="decide", backend="mock", payload="p",
                 payload_provenance_class="learner", payload_source_learners=dumps([learner]), response="r",
                 response_provenance_class="system", response_source_learners="[]", outcome="ok",
                 created_at=now_iso())
    store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=? WHERE learner_id=?", (700 + learner, learner))
    return s, utt


def test_forget_learner_removes_every_store_and_every_derived_copy(store, settings):
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    book, page, rev = seed.book_page(store, TEXT)
    _, ada_utt = _history(store, ada, book, page, rev)
    ben_session, _ = _history(store, ben, book, page, rev)
    # Ben's records that quote Ada: an assessment and a Brain call
    _activity(store, ben_session, assessment="Ada helped", sources=[ben, ada])
    store.insert("brain_calls", session_id=ben_session, purpose="judge", backend="mock", payload="Ada said x",
                 payload_provenance_class="derived_from_learner", payload_source_learners=dumps([ada, ben]),
                 response_provenance_class="system", response_source_learners="[]", outcome="ok",
                 created_at=now_iso())
    span = corrections.locate(TEXT, "trees", near=0)
    corrections.apply_correction(store, page_id=page, revision_id=rev, char_start=span[0], char_end=span[1],
                                 new_text="tree", source="voice", learner_id=ada, utterance_id=ada_utt)
    (settings.data_dir / "learners" / str(ada)).mkdir(parents=True)
    (settings.data_dir / "learners" / str(ada) / "voice.npy").write_bytes(b"x")

    rep = records.forget_learner(store, ada, settings.data_dir)

    assert learner_store.get(store, ada) is None
    for table in ("reading_sessions", "knowledge_items", "encounters", "difficulties", "anki_outbox",
                  "review_answers", "learner_notes", "book_notes", "retrieval_events", "consents", "egress_log"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table} WHERE learner_id=?", (ada,))["n"] == 0, table
    assert store.one("SELECT COUNT(*) AS n FROM utterances WHERE source_learners LIKE ?", (f"%{ada}%",))["n"] == 0
    for t, src in (("activities", "assessment_source_learners"), ("brain_calls", "payload_source_learners")):
        assert store.one(f"SELECT COUNT(*) AS n FROM {t} WHERE EXISTS(SELECT 1 FROM json_each({src}) "
                         "WHERE value=?)", (ada,))["n"] == 0
    assert store.one("SELECT assessment FROM activities WHERE session_id=? AND assessment_provenance_class='system' "
                     "AND kind='read_listen' ORDER BY id DESC", (ben_session,))["assessment"] is None
    assert store.one("SELECT COUNT(*) AS n FROM brain_calls WHERE session_id=?", (ben_session,))["n"] == 1
    # Ben keeps everything of his own
    assert store.one("SELECT COUNT(*) AS n FROM knowledge_items WHERE learner_id=?", (ben,))["n"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM reading_sessions WHERE learner_id=?", (ben,))["n"] == 1
    # the correction stays as book text, unlinked; the name is a household term now
    c = store.one("SELECT * FROM corrections")
    assert (c["source_learner_id"], c["utterance_id"], c["forgotten"]) == (None, None, 1)
    assert store.one("SELECT term, kind FROM household_terms")[:] == ("Ada", "name")
    assert not (settings.data_dir / "learners" / str(ada)).exists()
    assert rep.anki_notes == [700 + ada] and rep.deck == "Leafi Ada #1" and rep.sessions == 1
    assert store.one("PRAGMA foreign_key_check") is None
    # the reached rows are gone with the session: one of each remains, Ben's
    for table in ("cycles", "observations", "practices", "miscues", "page_reads", "book_notes", "review_answers"):
        assert store.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 1, table


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


def test_another_learners_utterance_quoting_the_learner_loses_its_text_not_its_row(store, settings):
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    book, page, rev = seed.book_page(store, TEXT)
    s = seed.session(store, book, learner_id=ben)
    store.execute("UPDATE reading_sessions SET ended_at=? WHERE id=?", (now_iso(), s))
    utt = store.insert("utterances", session_id=s, text="Ada told me", kind="question",
                       provenance_class="derived_from_learner", source_learners=dumps([ada, ben]), created_at=now_iso())
    corr = corrections.record_unlocated(store, revision_id=rev, old_text="a", new_text="b", source="parent",
                                        learner_id=None, utterance_id=utt)
    records.forget_learner(store, ada, settings.data_dir)
    u = store.one("SELECT * FROM utterances WHERE id=?", (utt,))
    assert (u["text"], u["source_learners"]) == ("", "[]")
    assert store.one("SELECT utterance_id FROM corrections WHERE id=?", (corr,))["utterance_id"] == utt


def test_cards_to_remove_survive_a_forget_stopped_between_batches(store, settings, monkeypatch):
    ada = seed.learner(store, "Ada")
    book, page, rev = seed.book_page(store, TEXT)
    _history(store, ada, book, page, rev)
    monkeypatch.setattr(records, "_purge_derived", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):  # the outbox rows are already deleted at this point
        records.forget_learner(store, ada, settings.data_dir)
    assert store.one("SELECT COUNT(*) AS n FROM anki_outbox")["n"] == 0
    monkeypatch.undo()
    assert records.forget_learner(store, ada, settings.data_dir).anki_notes == [700 + ada]


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


def test_a_derived_write_naming_the_learner_is_refused_while_forgetting_and_after(store, settings):
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ada,))  # what the first step commits
    note = dict(text="x", provenance_class="derived_from_learner", source_learners=dumps([ada, ben]),
                created_at=now_iso())
    with pytest.raises(learner_store.LearnerUnavailable):
        learner_store.insert(store, "learner_notes", ben, sources=[ada, ben], **note)
    records.forget_learner(store, ada, settings.data_dir)
    with pytest.raises(learner_store.LearnerUnavailable):
        learner_store.insert(store, "learner_notes", ben, sources=[ada, ben], **note)


def test_the_final_rescan_removes_a_copy_written_between_batches(store, settings, monkeypatch):
    ada, ben = seed.learner(store, "Ada"), seed.learner(store, "Ben")
    calls = []
    real = records._purge_derived

    def slip_in(st, learner_id, report):
        real(st, learner_id, report)
        calls.append(1)
        if len(calls) == 1:  # a writer that skipped the fence lands after the first sweep
            st.insert("learner_notes", learner_id=ben, text="x", provenance_class="derived_from_learner",
                      source_learners=dumps([ada]), created_at=now_iso())

    monkeypatch.setattr(records, "_purge_derived", slip_in)
    records.forget_learner(store, ada, settings.data_dir)
    assert store.one("SELECT COUNT(*) AS n FROM learner_notes")["n"] == 0


def test_forget_learner_resumes_after_a_stop_half_way(store, settings, monkeypatch):
    ada = seed.learner(store, "Ada")
    book, page, rev = seed.book_page(store, TEXT)
    _history(store, ada, book, page, rev)
    monkeypatch.setattr(records, "_purge_derived", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        records.forget_learner(store, ada, settings.data_dir)
    assert learner_store.get(store, ada)["forgetting"] == 1
    assert learner_store.enrolled(store) == []  # never offered while marked
    monkeypatch.undo()
    records.forget_learner(store, ada, settings.data_dir)
    assert learner_store.get(store, ada) is None


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
    learner_store.insert(store, "book_notes", ada, book_id=book, text="a fox story", provenance_class="system",
                         source_learners="[]", created_at=now_iso())
    records.forget_book(store, book)
    assert store.one("SELECT COUNT(*) AS n FROM book_notes")["n"] == 0


def test_forget_learner_command_confirms_first(settings, monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    with Store(settings.db_path) as store:
        ada = seed.learner(store, "Ada")
    assert cli.main(["forget", "--learner", str(ada)]) == 1
    assert "Run again with --yes" in capsys.readouterr().out
    with Store(settings.db_path) as store:
        assert learner_store.get(store, ada) is not None
    assert cli.main(["forget", "--learner", str(ada), "--yes"]) == 0
    assert "forgot learner" in capsys.readouterr().out
    with Store(settings.db_path) as store:
        assert learner_store.get(store, ada) is None
