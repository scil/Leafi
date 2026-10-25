"""Migration 7 (ADR-0021 E8): the provenance columns go through the existing runner (a frozen `SCHEMA_V6`, `_step`
to the new `SCHEMA`); every row and index survives; the cleanup (`VACUUM`, a TRUNCATE checkpoint) removes the
dropped values from the file and its -wal, and reruns on a file already at 7. Real SQLite files, never mocked."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from leafi.core import storage
from leafi.core.storage import SCHEMA_VERSION, Store
from tests.test_migration_5 import _counts, _version, v4_file
from tests.test_migration_6 import V5_ROWS, v5_file

CANARY = "[987654321]"  # a value no other column holds, in a dropped `*_source_learners` column

V6_ROWS = f"""
INSERT INTO learners(id, kind, display_name, alias, created_at) VALUES(1, 'learner', 'Mia', 'Mimi', 't');
INSERT INTO reading_sessions(id, learner_id, started_at, ended_at, mode, summary, post_done_at)
    VALUES(1, 1, 't', 't2', 'voice', '{{}}', 't2');
INSERT INTO activities(id, session_id, kind, status, started_at, outcome, outcome_provenance_class,
    outcome_source_learners, assessment, assessment_provenance_class, assessment_source_learners)
    VALUES(1, 1, 'read_listen', 'completed', 't', '{{}}', 'system', '[]', 'fine', 'derived_from_learner', '{CANARY}');
INSERT INTO utterances(id, session_id, text, kind, provenance_class, source_learners, created_at)
    VALUES(1, 1, 'the wind blue', 'reading', 'learner', '[1]', 't');
INSERT INTO brain_calls(id, session_id, activity_id, purpose, backend, payload, payload_provenance_class,
    payload_source_learners, response, response_provenance_class, response_source_learners, outcome, created_at)
    VALUES(1, 1, 1, 'decide', 'mock', '{{}}', 'system', '[]', 'r', 'system', '[]', 'ok', 't');
INSERT INTO knowledge_items(id, learner_id, kind, language, key, anki_item_key, created_at, updated_at)
    VALUES(1, 1, 'word', 'en', 'blew', 'k1', 't', 't');
INSERT INTO encounters(id, learner_id, knowledge_item_id, session_id, context_sentence, context_provenance_class,
    context_source_learners, explanation_en, explanation_provenance_class, explanation_source_learners, trigger,
    created_at) VALUES(1, 1, 1, 1, 'The wind blew.', 'page', '[]', 'moved air', 'learner', '[1]', 'explain', 't');
INSERT INTO learner_notes(id, learner_id, session_id, text, provenance_class, source_learners, created_at)
    VALUES(1, 1, 1, 'likes foxes', 'derived_from_learner', '[1]', 't');
INSERT INTO anki_outbox(id, learner_id, knowledge_item_id, op, state, updated_at, front, card_provenance_class,
    card_source_learners) VALUES(1, 1, 1, 'add', 'pending', 't', 'blew', 'derived_from_learner', '[1]')
"""


def v6_file(path, rows: str = V6_ROWS) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    for stmt in storage._split(storage.SCHEMA_V6):
        conn.execute(stmt)
    conn.execute(storage.SEEDS)
    conn.execute("PRAGMA user_version = 6")
    for stmt in storage._split(rows):
        conn.execute(stmt)
    conn.close()


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def v6(tmp_path):
    path = tmp_path / "leafi.db"
    v6_file(path)
    return path


def test_v6_to_v7_drops_every_provenance_column_and_equals_a_fresh_file(v6, tmp_path):
    before = _counts(v6)
    res = storage.migrate_file(v6)
    assert res.from_version == 6 and res.cleaned
    assert set(res.rebuilt) == {"activities", "brain_calls", "utterances", "encounters", "learner_notes",
                                "book_notes", "anki_outbox"}
    migrated = sqlite3.connect(str(v6))
    fresh = Store(tmp_path / "fresh.db")
    assert storage.schema_of(migrated) == storage.schema_of(fresh.conn)
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 7
    for table in ("activities", "brain_calls", "utterances", "encounters", "learner_notes", "book_notes",
                  "anki_outbox"):
        cols = _columns(migrated, table)
        assert not {c for c in cols if c.endswith(("provenance_class", "source_learners"))}, table
    assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    assert migrated.execute("SELECT assessment FROM activities").fetchone()[0] == "fine"
    migrated.close()
    fresh.close()
    assert {t: n for t, n in _counts(v6).items() if t in before} == before


def test_the_dropped_values_leave_the_file_and_its_wal(v6):
    storage.migrate_file(v6)
    wal = Path(str(v6) + "-wal")
    data = v6.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
    assert CANARY.encode() not in data


def test_files_at_4_and_5_reach_7_in_one_run(tmp_path):
    v4, v5 = tmp_path / "v4.db", tmp_path / "v5.db"
    v4_file(v4)
    v5_file(v5, V5_ROWS)
    storage.migrate_file(v4, "Ada")
    storage.migrate_file(v5)
    assert _version(v4) == _version(v5) == 7
    for path in (v4, v5):
        conn = sqlite3.connect(str(path))
        assert "provenance_class" not in _columns(conn, "utterances")
        conn.close()


def test_a_failure_in_step_7_leaves_version_6_and_reruns(v6):
    before = _counts(v6)

    def fail(table: str) -> None:
        if table == "anki_outbox":
            raise RuntimeError("power cut")

    with pytest.raises(RuntimeError, match="power cut"):
        storage.migrate_file(v6, _hook=fail)
    assert _version(v6) == 6 and _counts(v6) == before
    storage.migrate_file(v6)
    assert _version(v6) == 7


def test_a_cleanup_cut_off_after_the_commit_completes_on_the_next_run(v6, monkeypatch):
    real = storage._cleanup
    monkeypatch.setattr(storage, "_cleanup", lambda conn: False)  # the process died before VACUUM
    res = storage.migrate_file(v6)
    assert _version(v6) == 7 and not res.cleaned
    monkeypatch.setattr(storage, "_cleanup", real)
    again = storage.migrate_file(v6)
    assert again.from_version == 7 and again.cleaned
    wal = Path(str(v6) + "-wal")
    assert CANARY.encode() not in v6.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def test_the_migrate_command_reports_the_cleanup(settings, monkeypatch, capsys):
    from leafi import cli

    path = settings.db_path
    path.parent.mkdir(parents=True)
    v6_file(path)
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "from schema 6 to 7" in out and "cleanup complete" in out and "ADR-0019" in out
    assert cli.main(["migrate"]) == 0
    assert "already at schema 7; cleanup complete" in capsys.readouterr().out
