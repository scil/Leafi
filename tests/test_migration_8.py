"""Migration 8 (M7 design D17, D19, rev 11): `item_status_events` with one `card_ack` per acknowledged card and
`decision_records`, through the existing runner (a frozen `SCHEMA_V7`); the `migrate` command re-folds every item's
status, also on a rerun. Real SQLite files, never mocked."""

from __future__ import annotations

import sqlite3

import pytest

from leafi.core import storage
from leafi.core.storage import SCHEMA_VERSION, Store
from tests.test_migration_5 import _counts, _version
from tests.test_migration_7 import v6_file

V7_ROWS = """
INSERT INTO learners(id, kind, display_name, created_at) VALUES(1, 'learner', 'Mia', 't');
INSERT INTO learners(id, kind, display_name, created_at) VALUES(2, 'learner', 'Leo', 't');
INSERT INTO reading_sessions(id, learner_id, started_at, ended_at, mode, summary, post_done_at)
    VALUES(1, 1, 't', 't2', 'voice', '{}', 't2');
INSERT INTO activities(id, session_id, kind, status, started_at) VALUES(1, 1, 'recall_items', 'completed', 't');
INSERT INTO knowledge_items(id, learner_id, kind, language, key, status, anki_item_key, created_at, updated_at)
    VALUES(1, 1, 'word', 'en', 'blew', 'known', 'k1', 't', 't');
INSERT INTO knowledge_items(id, learner_id, kind, language, key, status, anki_item_key, created_at, updated_at)
    VALUES(2, 1, 'word', 'en', 'through', 'learning', 'k2', 't', 't');
INSERT INTO knowledge_items(id, learner_id, kind, language, key, status, anki_item_key, created_at, updated_at)
    VALUES(3, 2, 'word', 'en', 'never', 'new', 'k3', 't', 't');
INSERT INTO anki_outbox(id, learner_id, knowledge_item_id, op, state, card_ids, updated_at)
    VALUES(1, 1, 1, 'add', 'acked', '[11, 12]', '2026-10-01T10:00:00+00:00');
INSERT INTO anki_outbox(id, learner_id, knowledge_item_id, op, state, card_ids, updated_at)
    VALUES(2, 1, 1, 'update', 'acked', '[11, 12]', '2026-10-05T10:00:00+00:00');
INSERT INTO anki_outbox(id, learner_id, knowledge_item_id, op, state, card_ids, updated_at)
    VALUES(3, 2, 3, 'add', 'pending', '[31]', '2026-10-02T10:00:00+00:00');
INSERT INTO anki_outbox(id, learner_id, knowledge_item_id, op, state, card_ids, updated_at)
    VALUES(4, 2, 3, 'add', 'acked', '[]', '2026-10-02T10:00:00+00:00')
"""
# item 2: six successes over three days, cached `learning` by M6 → `known` after the re-fold
V7_ROWS += "".join(
    f";\nINSERT INTO retrieval_events(learner_id, item_id, activity_id, at, day, outcome, evidence) "
    f"VALUES(1, 2, 1, '{d}T10:00:0{i}', '{d}', 'success', 'typed')"
    for i, d in enumerate(["2026-10-01", "2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03", "2026-10-03"]))


def v7_file(path, rows: str = V7_ROWS) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    for stmt in storage._split(storage.SCHEMA_V7):
        conn.execute(stmt)
    conn.execute(storage.SEEDS)
    conn.execute("PRAGMA user_version = 7")
    for stmt in storage._split(rows):
        conn.execute(stmt)
    conn.close()


@pytest.fixture
def v7(tmp_path):
    path = tmp_path / "leafi.db"
    v7_file(path)
    return path


def test_the_frozen_v7_shape_has_neither_new_table(v7):
    conn = sqlite3.connect(str(v7))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "item_status_events" not in tables and "decision_records" not in tables
    assert {"knowledge_items", "anki_outbox", "retrieval_events"} <= tables


def test_v7_to_v8_adds_both_tables_backfills_one_ack_per_card_and_equals_a_fresh_file(v7, tmp_path):
    before = _counts(v7)
    res = storage.migrate_file(v7)
    assert res.from_version == 7 and res.cleaned and res.rebuilt == []
    assert set(res.created) == {"item_status_events", "decision_records"}
    migrated = sqlite3.connect(str(v7))
    with Store(tmp_path / "fresh.db") as fresh:
        assert storage.schema_of(migrated) == storage.schema_of(fresh.conn)
    assert _version(v7) == SCHEMA_VERSION == 8
    rows = migrated.execute("SELECT learner_id, item_id, at, day, event, source, card_id, session_id "
                            "FROM item_status_events ORDER BY id").fetchall()
    # the add and its update carry the same ids: one ack each, at the earliest acknowledgement; pending and
    # card-less rows give none
    assert rows == [(1, 1, "2026-10-01T10:00:00+00:00", "2026-10-01", "card_ack", "anki", 11, None),
                    (1, 1, "2026-10-01T10:00:00+00:00", "2026-10-01", "card_ack", "anki", 12, None)]
    after = _counts(v7)
    assert {t: n for t, n in after.items() if t not in ("item_status_events", "decision_records")} == before
    assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_v6_file_reaches_8_in_one_run(tmp_path):
    path = tmp_path / "leafi.db"
    v6_file(path)
    res = storage.migrate_file(path)
    assert res.from_version == 6 and _version(path) == SCHEMA_VERSION
    with Store(tmp_path / "fresh.db") as fresh:
        assert storage.schema_of(sqlite3.connect(str(path))) == storage.schema_of(fresh.conn)


def test_a_failure_in_step_8_leaves_version_7_and_reruns(v7, monkeypatch):
    before = _counts(v7)
    real = storage._v8_backfill

    def boom(conn):
        real(conn)
        raise RuntimeError("injected")

    monkeypatch.setattr(storage, "_v8_backfill", boom)
    with pytest.raises(RuntimeError):
        storage.migrate_file(v7)
    assert _version(v7) == 7 and _counts(v7) == before
    monkeypatch.setattr(storage, "_v8_backfill", real)
    storage.migrate_file(v7)
    assert _version(v7) == 8
    assert sqlite3.connect(str(v7)).execute("SELECT COUNT(*) FROM item_status_events").fetchone()[0] == 2


def test_a_schema_7_file_refuses_to_open(v7):
    with pytest.raises(storage.SchemaError):
        Store(v7)


def _statuses(path):
    return dict(sqlite3.connect(str(path)).execute("SELECT id, status FROM knowledge_items").fetchall())


def test_the_migrate_command_refolds_item_statuses_and_again_on_a_rerun(settings, monkeypatch, capsys):
    from leafi import cli

    path = settings.db_path
    path.parent.mkdir(parents=True)
    v7_file(path)
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert f"from schema 7 to {SCHEMA_VERSION}" in out and "item statuses re-folded (2 changed)" in out
    # item 1: `known` from M6's pre-answer interval, now a card with no observed state → learning;
    # item 2: six successes over three days → known; item 3: no evidence → new
    assert _statuses(path) == {1: "learning", 2: "known", 3: "new"}
    sqlite3.connect(str(path), isolation_level=None).execute("UPDATE knowledge_items SET status='new' WHERE id=2")
    assert cli.main(["migrate"]) == 0  # a crash before the re-fold is completed by rerunning the command
    assert "already at schema 8" in capsys.readouterr().out
    assert _statuses(path)[2] == "known"
