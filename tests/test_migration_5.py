"""Migration 5 (ADR-0018 §7.2): one transaction under an exclusive lock, a backup first, schema equal to a fresh
file, every version-4 row kept and owned by the first learner. Real SQLite files, never mocked."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap

import pytest

from leafi.core import storage
from leafi.core.storage import SCHEMA_VERSION, Store

V4_ROWS = """
INSERT INTO books(id, title, language, created_at) VALUES(1, 'Wind', 'en', 't');
INSERT INTO pages(id, book_id, printed_number, created_at) VALUES(1, 1, 3, 't');
INSERT INTO page_revisions(id, page_id, rev, text, source, tokenizer_version, created_at)
    VALUES(1, 1, 1, 'The wind blew.', 'ocr', '1', 't');
INSERT INTO page_images(id, page_id, path, captured_at) VALUES(1, 1, 'x.png', 't');
INSERT INTO reading_sessions(id, book_id, started_at, ended_at, mode) VALUES(1, 1, 't', 't2', 'voice');
INSERT INTO page_reads(id, session_id, page_id, page_revision_id, started_at) VALUES(1, 1, 1, 1, 't');
INSERT INTO utterances(id, page_read_id, page_revision_id, session_id, text, kind, created_at)
    VALUES(1, 1, 1, 1, 'the wind blue', 'reading', 't');
INSERT INTO utterances(id, page_read_id, page_revision_id, session_id, text, kind, created_at)
    VALUES(2, 1, 1, NULL, 'blew', 'practice', 't');
INSERT INTO observations(id, utterance_id, kind, token_start, token_end, heard_text, created_at)
    VALUES(1, 1, 'substituted', 2, 3, 'blue', 't');
INSERT INTO miscues(id, observation_id, page_read_id, page_revision_id, expected, expected_token_index,
    expected_char_span, heard, status, unsure_reason, updated_at)
    VALUES(1, 1, 1, 1, 'blew', 2, '[9,13]', 'blue', 'unsure', 'disagreed', 't');
INSERT INTO miscues(id, observation_id, page_read_id, page_revision_id, expected, expected_token_index,
    expected_char_span, heard, status, updated_at) VALUES(2, NULL, 1, 1, 'wind', 1, '[4,8]', NULL, 'candidate', 't');
INSERT INTO practices(id, miscue_id, attempt, outcome, evidence, created_at) VALUES(1, 1, 1, 'disagreed', 'none', 't');
INSERT INTO knowledge_items(id, kind, language, key, anki_item_key, created_at, updated_at)
    VALUES(1, 'word', 'en', 'blew', 'k1', 't', 't');
INSERT INTO encounters(id, knowledge_item_id, session_id, page_revision_id, context_sentence, explanation_en,
    trigger, created_at) VALUES(1, 1, 1, 1, 'The wind blew.', 'moved air', 'explain', 't');
INSERT INTO difficulties(id, miscue_key, weight, kind, updated_at) VALUES(1, 'blew', 0.3, 'watch', 't');
INSERT INTO anki_outbox(id, knowledge_item_id, op, state, anki_note_id, updated_at, attempted_fields)
    VALUES(1, 1, 'add', 'acked', 77, 't', '{}');
INSERT INTO review_answers(id, knowledge_item_id, card_id, ease, state, created_at) VALUES(1, 1, 5, 3, 'acked', 't');
INSERT INTO corrections(id, page_revision_id, char_start, char_end, old_text, new_text, source, utterance_id,
    created_at) VALUES(1, 1, 4, 8, 'wind', 'wind', 'voice', 1, 't');
INSERT INTO corrections(id, page_revision_id, old_text, new_text, source, created_at)
    VALUES(2, 1, 'x', 'y', 'parent', 't');
INSERT INTO lexicon(word, language, source, book_id, updated_at) VALUES('wind', 'en', 'book', 1, 't');
INSERT INTO learner_profile(key, value, updated_at) VALUES('age', '10', 't');
INSERT INTO alert_outbox(key, state, reason, created_at) VALUES('camera', 'down', 'x', 't');
INSERT INTO service_state(service, updated_at) VALUES('camera', 't')
"""


def v4_file(path, rows: str = V4_ROWS) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    for step in storage.LEGACY_STEPS:
        for stmt in storage._split(step):
            conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {len(storage.LEGACY_STEPS)}")
    for stmt in storage._split(rows):
        conn.execute(stmt)
    conn.close()


def _counts(path) -> dict[str, int]:
    conn = sqlite3.connect(str(path))
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                            "AND name NOT LIKE 'sqlite_%'")]
        return {n: conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}
    finally:
        conn.close()


def _version(path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def old(tmp_path):
    path = tmp_path / "leafi.db"
    v4_file(path)
    return path


def test_migrated_schema_equals_a_fresh_one(old, tmp_path):
    res = storage.migrate_file(old, "Ada")
    assert res.from_version == 4 and res.learner_id == 1
    fresh = Store(tmp_path / "fresh.db")
    migrated = sqlite3.connect(str(old))
    assert storage.schema_of(migrated) == storage.schema_of(fresh.conn)
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    migrated.close()


def test_every_row_is_kept_and_owned_by_the_first_learner(old):
    before = _counts(old)
    res = storage.migrate_file(old, " Ada ", learner_settings={"anki.deck": "Leafi"})
    after = _counts(old)
    assert {t: n for t, n in after.items() if t in before} == before
    with Store(old) as store:
        (ada,) = store.all("SELECT * FROM learners")
        assert (ada["id"], ada["kind"], ada["display_name"], ada["forgetting"]) == (res.learner_id, "learner", "Ada", 0)
        for table in ("reading_sessions", "knowledge_items", "encounters", "difficulties", "anki_outbox",
                      "review_answers"):
            assert {r["learner_id"] for r in store.all(f"SELECT learner_id FROM {table}")} == {ada["id"]}, table
        # provenance (ADR-0018 §3): learner text of the first learner, page-derived fields `page`
        u = store.all("SELECT session_id, provenance_class, source_learners FROM utterances ORDER BY id")
        assert [tuple(r) for r in u] == [(1, "learner", "[1]"), (1, "learner", "[1]")]  # NULL session from its read
        e = store.one("SELECT * FROM encounters")
        assert (e["context_provenance_class"], e["context_source_learners"]) == ("page", "[]")
        assert (e["explanation_provenance_class"], e["explanation_source_learners"]) == ("learner", "[1]")
        assert store.one("SELECT card_provenance_class FROM anki_outbox")[0] == "learner"
        # corrections: the learner's own, the parent's stays without one
        c = {r["id"]: (r["source_learner_id"], r["forgotten"]) for r in store.all("SELECT * FROM corrections")}
        assert c == {1: (1, 0), 2: (None, 0)}
        assert {r["id"]: r["origin"] for r in store.all("SELECT id, origin FROM miscues")} == {
            1: "substitution", 2: "deletion"}
        from leafi.study import anki

        assert anki.deck_for(store, ada["id"]) == "Leafi"  # the household's existing deck stays this child's


def test_new_check_values_are_accepted_after_migration(old):
    storage.migrate_file(old, "Ada")
    with Store(old) as store:
        store.execute("UPDATE knowledge_items SET kind='pattern', status='ignored'")
        store.execute("UPDATE encounters SET trigger='teach_incorrect'")
        store.execute("UPDATE review_answers SET ease=4")
        store.execute("UPDATE miscues SET status='unsure', unsure_reason='unclear' WHERE id=2")
        store.execute("UPDATE practices SET outcome='idle'")
        store.execute("INSERT INTO observations(utterance_id, kind, word_count, created_at) "
                      "VALUES(1, 'unaligned', 3, 't')")
        with pytest.raises(sqlite3.IntegrityError):  # token columns are NULL for `unaligned` only
            store.execute("INSERT INTO observations(utterance_id, kind, created_at) VALUES(1, 'matched', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            store.execute("UPDATE corrections SET source_learner_id=NULL WHERE id=1")  # a learner's, not forgotten
        store.execute("UPDATE corrections SET source_learner_id=NULL, forgotten=1 WHERE id=1")


def test_a_failure_mid_rebuild_leaves_version_4_intact_and_the_command_reruns(old):
    before = _counts(old)

    def fail_at_miscues(table: str) -> None:
        if table == "miscues":
            raise RuntimeError("power cut")

    with pytest.raises(RuntimeError, match="power cut"):
        storage.migrate_file(old, "Ada", _hook=fail_at_miscues)
    assert _version(old) == 4
    assert _counts(old) == before  # no learners table, no rebuilt table, no row lost
    assert storage.migrate_file(old, "Ada").learner_id == 1
    assert _version(old) == SCHEMA_VERSION


def test_a_foreign_key_violation_rolls_back(tmp_path):
    path = tmp_path / "leafi.db"
    v4_file(path, V4_ROWS + ";\nINSERT INTO page_reads(id, session_id, page_id, page_revision_id, started_at) "
                            "VALUES(9, 404, 1, 1, 't')")
    with pytest.raises(storage.SchemaError, match="foreign key"):
        storage.migrate_file(path, "Ada")
    assert _version(path) == 4


def test_the_backup_is_made_first_and_restores(old, tmp_path):
    res = storage.migrate_file(old, "Ada", backup_dir=tmp_path / "bk")
    assert res.backup.parent == tmp_path / "bk" and _version(res.backup) == 4
    assert _counts(res.backup)["miscues"] == 2
    storage.restore_file(old, res.backup)
    assert _version(old) == 4


def test_refused_while_a_store_is_open_in_this_process(old, tmp_path):
    fresh = tmp_path / "other.db"
    with Store(fresh):
        pass
    holder = storage._FileLock(old, exclusive=False)  # what an open Store holds
    try:
        with pytest.raises(storage.DatabaseInUse, match="another Leafi process"):
            storage.migrate_file(old, "Ada")
    finally:
        holder.release()
    assert _version(old) == 4
    storage.migrate_file(old, "Ada")


def test_refused_while_another_process_has_the_database_open(old):
    script = textwrap.dedent(f"""
        import sys, time, portalocker
        f = open({str(storage.lock_path(old))!r}, "a+")
        portalocker.lock(f, portalocker.LOCK_SH | portalocker.LOCK_NB)
        print("held", flush=True)
        sys.stdin.readline()
    """)
    p = subprocess.Popen([sys.executable, "-I", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True)
    try:
        assert p.stdout.readline().strip() == "held"
        with pytest.raises(storage.DatabaseInUse):
            storage.migrate_file(old, "Ada")
    finally:
        p.communicate("\n", timeout=10)
    assert _version(old) == 4
    storage.migrate_file(old, "Ada")


def test_an_up_to_date_file_is_left_alone(tmp_path):
    path = tmp_path / "leafi.db"
    Store(path).close()
    assert storage.migrate_file(path, "Ada").learner_id is None


def test_migrate_command(old, settings, monkeypatch, capsys):
    from leafi import cli

    path = settings.db_path
    path.parent.mkdir(parents=True)
    v4_file(path)
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    assert cli.main(["study", "--text", "--mock"]) == 2  # refuses and names the command
    assert "leafi migrate --learner" in capsys.readouterr().out
    assert cli.main(["backup"]) == 0  # works below the latest version
    assert cli.main(["migrate"]) == 2
    assert cli.main(["migrate", "--learner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "first learner #1 Ada" in out
    assert cli.main(["migrate", "--learner", "Ada"]) == 0
    assert "already at schema" in capsys.readouterr().out
