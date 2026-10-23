"""Migration 6 (M5 design D19): v5 → v6 without a learner, schema and seed rows equal to a fresh file, every row
kept with its owner, the old `REDACT_TERMS` imported as names, a v4 file brought to 6 in one run. Real SQLite
files, never mocked."""

from __future__ import annotations

import sqlite3

import pytest

from leafi.core import storage
from leafi.core.storage import SCHEMA_VERSION, Store
from tests.test_migration_5 import _counts, _version, v4_file

V5_ROWS = """
INSERT INTO learners(id, kind, display_name, alias, created_at) VALUES(1, 'learner', 'Mia', 'Mimi', 't');
INSERT INTO learners(id, kind, display_name, created_at) VALUES(2, 'learner', 'Leo', 't');
INSERT INTO reading_sessions(id, learner_id, started_at, ended_at, mode, summary)
    VALUES(1, 1, 't', 't2', 'voice', '{}');
INSERT INTO egress_log(id, destination, purpose, learner_id, session_id, payload_size, body_hmac, status,
    transmitted_attempts, created_at, updated_at) VALUES(1, 'anthropic', 'generate', 1, 1, 10, 'h', 'sent', 1, 't', 't');
INSERT INTO egress_log(id, destination, purpose, payload_size, body_hmac, status, created_at, updated_at)
    VALUES(2, 'healthchecks', 'ops', 0, 'h', 'sent', 't', 't');
INSERT INTO household_terms(id, term, kind, created_at) VALUES(1, 'Oakwood', 'school', 't')
"""


def v5_file(path, rows: str = V5_ROWS) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    for stmt in storage._split(storage.SCHEMA_V5):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 5")
    for stmt in storage._split(rows):
        conn.execute(stmt)
    conn.close()


def _rows(conn, sql: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(sql)]


@pytest.fixture
def v5(tmp_path):
    path = tmp_path / "leafi.db"
    v5_file(path)
    return path


def test_v5_to_v6_needs_no_learner_and_equals_a_fresh_file(v5, tmp_path):
    res = storage.migrate_file(v5)
    assert (res.from_version, res.learner_id) == (5, None)
    assert set(res.created) == {"pseudonyms", "privacy_state"}
    assert set(res.rebuilt) == {"reading_sessions", "egress_log"}
    fresh = Store(tmp_path / "fresh.db")
    migrated = sqlite3.connect(str(v5))
    assert storage.schema_of(migrated) == storage.schema_of(fresh.conn)
    assert _rows(migrated, "SELECT * FROM privacy_state") == _rows(fresh.conn, "SELECT * FROM privacy_state")
    assert migrated.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 6
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _rows(migrated, "SELECT COUNT(*) FROM learners") == [(2,)]  # no learner created
    migrated.close()
    fresh.close()


def test_every_v5_row_is_kept_with_its_owner(v5):
    before = _counts(v5)
    storage.migrate_file(v5)
    after = _counts(v5)
    assert {t: n for t, n in after.items() if t in before} == before
    with Store(v5) as store:
        assert _rows(store.conn, "SELECT id, learner_id, purpose, transmitted_attempts, owner FROM egress_log "
                                 "ORDER BY id") == [(1, 1, "generate", 1, None), (2, None, "ops", 0, None)]
        s = store.one("SELECT learner_id, summary, owner, post_done_at FROM reading_sessions")
        assert tuple(s) == (1, "{}", None, None)


def test_new_values_are_accepted_after_migration_and_learner_ids_stay_required(v5):
    storage.migrate_file(v5)
    with Store(v5) as store:
        store.execute("INSERT INTO egress_log(destination, purpose, learner_id, payload_size, body_hmac, status, "
                      "owner, created_at, updated_at) VALUES('telegram', 'notify', 1, 5, 'h', 'sending', '9:1', 't', 't')")
        with pytest.raises(sqlite3.IntegrityError):  # a study purpose still needs a learner
            store.execute("INSERT INTO egress_log(destination, purpose, payload_size, body_hmac, status, created_at, "
                          "updated_at) VALUES('bark', 'notify', 5, 'h', 'sending', 't', 't')")
        store.execute("INSERT INTO pseudonyms(entity, surrogate, created_at) VALUES('learner:1', 'Nola', 't')")
        with pytest.raises(sqlite3.IntegrityError):  # one surrogate per entity, never shared, any case
            store.execute("INSERT INTO pseudonyms(entity, surrogate, created_at) VALUES('learner:2', 'nola', 't')")


def test_legacy_terms_become_names_except_learners_and_existing_terms(v5):
    storage.migrate_file(v5, legacy_terms=["Mia", " mimi ", "Oakwood", "Grandma Rose", "Grandma Rose", " "])
    with Store(v5) as store:
        assert _rows(store.conn, "SELECT term, kind FROM household_terms ORDER BY id") == [
            ("Oakwood", "school"), ("Grandma Rose", "name")]
        assert store.one("SELECT value FROM privacy_state WHERE key='protected_version'")[0] == 1
        # idempotent: M5d runs the import again before the key goes
        assert storage.import_legacy_terms(store.conn, ["Grandma Rose", "Uncle Sam"]) == 1
        assert store.one("SELECT value FROM privacy_state WHERE key='protected_version'")[0] == 2


def test_protected_version_moves_with_every_name_change_and_nothing_else(tmp_path):
    with Store(tmp_path / "leafi.db") as store:
        def v() -> int:
            return store.one("SELECT value FROM privacy_state WHERE key='protected_version'")[0]

        assert v() == 0
        lid = store.insert("learners", kind="learner", display_name="Mia", created_at="t")
        assert v() == 1
        store.execute("UPDATE learners SET alias='Mimi' WHERE id=?", (lid,))
        store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (lid,))
        assert v() == 3
        store.execute("UPDATE learners SET settings='{\"bands.ask\": 2}', settings_version=2 WHERE id=?", (lid,))
        assert v() == 3  # harness settings are not names
        store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('Oakwood', 'school', 't')")
        store.execute("UPDATE household_terms SET kind='other'")
        store.execute("DELETE FROM household_terms")
        store.execute("DELETE FROM learners")
        assert v() == 7
        with pytest.raises(sqlite3.IntegrityError):
            with store.transaction():  # a rolled-back writer takes its bump with it
                store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('X', 'name', 't')")
                store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('x', 'name', 't')")
        assert v() == 7


def test_a_failure_in_step_6_leaves_version_5_and_reruns(v5):
    before = _counts(v5)

    def fail(table: str) -> None:
        if table == "egress_log":
            raise RuntimeError("power cut")

    with pytest.raises(RuntimeError, match="power cut"):
        storage.migrate_file(v5, _hook=fail)
    assert _version(v5) == 5
    assert _counts(v5) == before
    storage.migrate_file(v5)
    assert _version(v5) == 6


def test_v4_reaches_6_in_one_run_with_the_seed_rows(tmp_path):
    path = tmp_path / "leafi.db"
    v4_file(path)
    res = storage.migrate_file(path, "Ada", legacy_terms=["Ada", "Ben"])
    assert (res.from_version, res.learner_id) == (4, 1)
    assert _version(path) == 6
    with Store(path) as store:
        assert store.one("SELECT value FROM privacy_state WHERE key='protected_version'")[0] == 1
        assert _rows(store.conn, "SELECT term FROM household_terms") == [("Ben",)]


def test_a_v5_file_refuses_to_open_and_names_migrate_without_learner(v5):
    with pytest.raises(storage.NeedsMigration) as e:
        Store(v5)
    assert "leafi migrate`" in str(e.value) and "--learner" not in str(e.value)


def test_the_backup_restores_and_migrates_again(v5, tmp_path):
    res = storage.migrate_file(v5, backup_dir=tmp_path / "bk")
    assert _version(res.backup) == 5
    storage.restore_file(v5, res.backup)
    assert _version(v5) == 5
    storage.migrate_file(v5)
    assert _version(v5) == 6


def test_migrate_command_on_a_v5_file(settings, monkeypatch, capsys):
    from leafi import cli

    path = settings.db_path
    path.parent.mkdir(parents=True)
    v5_file(path)
    monkeypatch.setattr(cli, "_settings", lambda: settings.model_copy(update={"redact_terms": "Grandma Rose"}))
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "from schema 5 to 6" in out and "first learner" not in out
    with Store(path) as store:
        assert store.one("SELECT term FROM household_terms WHERE kind='name'")[0] == "Grandma Rose"
    assert cli.main(["migrate"]) == 0
    assert "already at schema 6" in capsys.readouterr().out
