"""Opening the database: three states and the shared lock (ADR-0018 §7.2). Real SQLite files."""

from __future__ import annotations

import sqlite3

import pytest

from leafi.core import storage
from leafi.core.storage import SCHEMA_VERSION, Store
from tests.test_migration_5 import v4_file


def test_an_empty_file_is_created_at_the_latest_schema_with_no_learner(tmp_path):
    with Store(tmp_path / "leafi.db") as store:
        assert store.version == SCHEMA_VERSION
        assert store.all("SELECT * FROM learners") == []
        assert storage.schema_of(store.conn) == storage.schema_of(storage._target())


def test_a_file_at_the_latest_version_opens(tmp_path):
    Store(tmp_path / "leafi.db").close()
    with Store(tmp_path / "leafi.db") as store:
        assert store.version == SCHEMA_VERSION


def test_a_file_with_data_below_the_latest_version_refuses_and_names_the_command(tmp_path):
    path = tmp_path / "leafi.db"
    v4_file(path)
    with pytest.raises(storage.NeedsMigration, match=r"leafi migrate --learner"):
        Store(path)
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4  # nothing written
    conn.close()
    storage.migrate_file(path, "Ada")  # the refused open released its lock


def test_a_newer_file_refuses(tmp_path):
    path = tmp_path / "leafi.db"
    Store(path).close()
    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(storage.SchemaError, match="newer"):
        Store(path)


def test_open_is_refused_while_a_migration_holds_the_lock(tmp_path):
    path = tmp_path / "leafi.db"
    Store(path).close()
    migration = storage._FileLock(path, exclusive=True)
    try:
        with pytest.raises(storage.DatabaseInUse, match="being migrated"):
            Store(path)
    finally:
        migration.release()
    Store(path).close()


def test_open_stores_share_the_lock_and_release_it_on_close(tmp_path):
    path = tmp_path / "leafi.db"
    a, b = Store(path), Store(path)
    with pytest.raises(storage.DatabaseInUse):
        storage._FileLock(path, exclusive=True)
    a.close()
    with pytest.raises(storage.DatabaseInUse):  # b still holds it
        storage._FileLock(path, exclusive=True)
    b.close()
    storage._FileLock(path, exclusive=True).release()


def test_an_opener_that_saw_version_0_while_another_created_the_schema_opens(tmp_path, monkeypatch):
    """Codex M3 #4: A reads version 0, B creates the schema, A must open, not demand a migration."""
    path = tmp_path / "leafi.db"
    Store(path).close()  # B's work, already committed
    real = Store.version.fget
    calls = {"n": 0}

    def stale_first_read(self):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else real(self)  # A's first read predates B's commit

    monkeypatch.setattr(Store, "version", property(stale_first_read))
    with Store(path) as store:
        assert real(store) == SCHEMA_VERSION
    assert calls["n"] >= 2


def test_an_unclosed_store_closes_its_connection_before_the_lock_is_free(tmp_path):
    """Codex M3 #5: a dropped Store must not leave a live connection once a migration can take the lock."""
    import gc

    path = tmp_path / "leafi.db"
    store = Store(path)
    conn = store.conn
    del store
    gc.collect()
    storage._FileLock(path, exclusive=True).release()  # the lock is free ...
    with pytest.raises(sqlite3.ProgrammingError):  # ... and the connection was closed first
        conn.execute("SELECT 1")


def test_memory_store_needs_no_lock():
    with Store(":memory:") as store:
        assert store.version == SCHEMA_VERSION
