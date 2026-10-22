import datetime as dt
import sqlite3

import agent.storage as storage


def test_record_and_week_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB", tmp_path / "t.db")
    storage.record("brush_pm", "verified", active_seconds=110, verified=True, confidence=0.9)
    storage.save("water", "present")
    st = storage.week_stats()
    assert st == {"done": 2, "missed": 0, "total": 2}


def test_streak(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB", tmp_path / "t.db")
    today = dt.date(2026, 8, 5)
    for d in range(1, 4):  # 昨天起往前 3 天全达标
        storage.record("brush_pm", "verified", on_date=today - dt.timedelta(days=d))
    storage.record("brush_pm", "missed", on_date=today - dt.timedelta(days=4))  # 第4天断了
    assert storage.streak_days(today=today) == 3
    storage.record("brush_am", "verified", on_date=today)  # 今天也打卡了
    assert storage.streak_days(today=today) == 4


def test_streak_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB", tmp_path / "t.db")
    assert storage.streak_days() == 0


def test_p0_old_db_migrates(tmp_path, monkeypatch):
    """P0 建的四列老库,P1 首次写入时应自动补列。"""
    dbp = tmp_path / "old.db"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE sessions(ts TEXT, date TEXT, task TEXT, status TEXT)")
    con.execute("INSERT INTO sessions VALUES('t', ?, 'brush_pm', 'present')",
                (dt.date.today().isoformat(),))
    con.commit()
    con.close()
    monkeypatch.setattr(storage, "DB", dbp)
    storage.record("water", "present")
    assert storage.week_stats()["total"] == 2


# ---------------------------------------------------------------- leafi store (data/leafi.db)

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from leafi.core.storage import MIGRATIONS, Store, now_iso  # noqa: E402

LEAFI_TABLES = {
    "books", "pages", "page_revisions", "page_images", "corrections", "reading_sessions", "page_reads",
    "utterances", "observations", "miscues", "practices", "knowledge_items", "encounters", "difficulties",
    "anki_outbox", "review_answers", "lexicon", "learner_profile",
}


def test_leafi_store_creates_schema_at_latest_version(tmp_path):
    store = Store(tmp_path / "leafi.db")
    names = {r["name"] for r in store.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert LEAFI_TABLES <= names
    assert store.version == len(MIGRATIONS)
    Store(tmp_path / "leafi.db")  # reopening is idempotent


def test_leafi_transaction_rolls_back_every_row(tmp_path):
    store = Store(tmp_path / "leafi.db")
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.insert("books", title="A", language="en", created_at=now_iso())
            raise RuntimeError("crash mid-transaction")
    assert store.one("SELECT COUNT(*) AS n FROM books")["n"] == 0


def test_leafi_failed_commit_rolls_back_and_frees_the_connection(tmp_path):
    """A COMMIT that fails (another process holds a read lock: SQLITE_BUSY) must not leave the transaction open;
    the next BEGIN IMMEDIATE on the same Store would otherwise fail (codex review of ADR-0017 v3, #14)."""
    path = tmp_path / "leafi.db"
    store = Store(path, journal_mode="delete")  # in WAL a reader no longer makes COMMIT fail (ADR-0019)
    store.conn.execute("PRAGMA busy_timeout = 0")
    reader = sqlite3.connect(str(path), isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM books").fetchall()  # holds a SHARED lock until it ends
    with pytest.raises(sqlite3.OperationalError):
        with store.transaction():
            store.insert("books", title="A", language="en", created_at=now_iso())
    reader.execute("COMMIT")
    reader.close()
    assert not store.conn.in_transaction
    assert store.one("SELECT COUNT(*) AS n FROM books")["n"] == 0
    with store.transaction():
        store.insert("books", title="B", language="en", created_at=now_iso())
    assert store.one("SELECT COUNT(*) AS n FROM books")["n"] == 1


# ---------------------------------------------------------------- WAL mode (ADR-0019)

import leafi.core.storage as leafi_storage  # noqa: E402


def _mode(path) -> str:
    c = sqlite3.connect(str(path))
    try:
        return c.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        c.close()


@pytest.mark.parametrize("version, safe", [
    ((3, 49, 1), False), ((3, 51, 2), False), ((3, 44, 5), False), ((3, 50, 6), False), ((3, 7, 0), False),
    ((3, 44, 6), True), ((3, 50, 7), True), ((3, 51, 3), True), ((3, 54, 1), True), ((4, 0, 0), True),
])
def test_wal_gate_follows_the_wal_reset_fix(version, safe):
    assert leafi_storage.wal_safe(version) is safe


@pytest.fixture
def fixed_library(monkeypatch):
    monkeypatch.setattr(leafi_storage, "_library_version", lambda: (3, 54, 1))


@pytest.fixture
def unfixed_library(monkeypatch):
    monkeypatch.setattr(leafi_storage, "_library_version", lambda: (3, 49, 1))


def test_new_store_is_wal_under_a_fixed_library(tmp_path, fixed_library):
    store = Store(tmp_path / "leafi.db")
    assert store.journal_mode == "wal"
    store.close()
    assert _mode(tmp_path / "leafi.db") == "wal"  # a property of the file


def test_rollback_file_switches_to_wal_on_next_open(tmp_path, fixed_library):
    Store(tmp_path / "leafi.db", journal_mode="delete").close()
    assert _mode(tmp_path / "leafi.db") == "delete"
    with Store(tmp_path / "leafi.db") as store:
        assert store.journal_mode == "wal"


def test_wal_file_returns_to_rollback_under_an_unfixed_library(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(leafi_storage, "_library_version", lambda: (3, 54, 1))
    Store(tmp_path / "leafi.db").close()
    monkeypatch.setattr(leafi_storage, "_library_version", lambda: (3, 49, 1))
    with caplog.at_level("WARNING"), Store(tmp_path / "leafi.db") as store:
        assert store.journal_mode == "delete"
    assert "3.49.1" in caplog.text
    assert _mode(tmp_path / "leafi.db") == "delete"


def test_locked_mode_switch_warns_and_the_open_succeeds(tmp_path, fixed_library, caplog):
    path = tmp_path / "leafi.db"
    Store(path, journal_mode="delete").close()
    other = sqlite3.connect(str(path), isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # a writer mid-transaction: the switch to WAL cannot happen now
    try:
        with caplog.at_level("WARNING"), Store(path) as store:
            assert store.journal_mode == "delete"
            assert store.one("SELECT COUNT(*) AS n FROM books")["n"] == 0
        assert "journal_mode" in caplog.text
    finally:
        other.execute("ROLLBACK")
        other.close()
    with Store(path) as store:  # the next open retries
        assert store.journal_mode == "wal"


def test_unfixed_library_refuses_a_wal_file_it_cannot_leave(tmp_path, monkeypatch):
    """Codex round 2, High: an unfixed library must not keep using a WAL file another connection holds."""
    path = tmp_path / "leafi.db"
    monkeypatch.setattr(leafi_storage, "_library_version", lambda: (3, 54, 1))
    fixed = Store(path)
    fixed.conn.execute("BEGIN")
    fixed.conn.execute("SELECT COUNT(*) FROM books").fetchall()  # a fixed process reading
    monkeypatch.setattr(leafi_storage, "_library_version", lambda: (3, 49, 1))
    with pytest.raises(leafi_storage.UnsafeSQLite, match="3.49.1"):
        Store(path)
    fixed.conn.execute("COMMIT")
    fixed.close()
    with Store(path) as store:  # once alone, the unfixed library returns the file to rollback mode
        assert store.journal_mode == "delete"


def test_blocked_checkpoint_reports_and_a_retry_empties_the_wal(tmp_path, fixed_library):
    path = tmp_path / "leafi.db"
    store = Store(path)
    store.conn.execute("PRAGMA busy_timeout = 0")
    store.insert("books", title="A", language="en", created_at=now_iso())
    reader = sqlite3.connect(str(path), isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM books").fetchall()  # pins a snapshot
    store.insert("books", title="B", language="en", created_at=now_iso())
    assert store.checkpoint() is False
    reader.execute("COMMIT")
    reader.close()
    assert leafi_storage.checkpoint_file(path) is True  # the supervisor's periodic retry
    assert Path(str(path) + "-wal").stat().st_size == 0
    store.close()


def test_memory_store_skips_the_mode_switch(fixed_library):
    with Store(":memory:") as store:
        assert store.journal_mode == "memory"


def test_open_reader_does_not_block_a_write_in_wal(tmp_path, fixed_library):
    path = tmp_path / "leafi.db"
    store = Store(path)
    store.conn.execute("PRAGMA busy_timeout = 0")
    reader = sqlite3.connect(str(path), isolation_level=None)
    reader.execute("BEGIN")
    assert reader.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
    with store.transaction():
        store.insert("books", title="A", language="en", created_at=now_iso())
    assert reader.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0  # its snapshot is unchanged
    reader.execute("COMMIT")
    assert reader.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    reader.close()
    store.close()


def test_two_stores_migrating_one_old_file_run_each_step_once(tmp_path, fixed_library):
    """migrate() reads user_version inside BEGIN IMMEDIATE, so a racing opener never reruns a step."""
    import threading

    for i in range(8):
        path = tmp_path / f"race{i}.db"
        old = sqlite3.connect(str(path), isolation_level=None)  # a version-1 file: steps 2.. still to run
        old.execute("PRAGMA journal_mode = WAL")  # rerunning step 2 (ALTER … ADD COLUMN) would fail
        for stmt in leafi_storage._split(MIGRATIONS[0]):
            old.execute(stmt)
        old.execute("PRAGMA user_version = 1")
        old.close()
        barrier, errors = threading.Barrier(2), []

        def open_store():
            barrier.wait()
            try:
                Store(path).close()
            except Exception as e:  # noqa: BLE001 - collected for the assertion
                errors.append(e)

        threads = [threading.Thread(target=open_store) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        with Store(path) as store:
            assert store.version == len(MIGRATIONS)


def test_forget_leaves_no_copy_of_the_deleted_text(tmp_path, fixed_library):
    from leafi.study.records import forget_session

    path = tmp_path / "leafi.db"
    store = Store(path)
    canary = "CANARY-utterance-7f3a"
    sid = store.insert("reading_sessions", started_at=now_iso(), mode="text")
    store.insert("utterances", session_id=sid, text=canary, kind="reading", created_at=now_iso())
    store.checkpoint()  # the row reaches the database file itself
    store.insert("utterances", session_id=sid, text=canary + "-wal", kind="reading", created_at=now_iso())
    forget_session(store, sid)
    data = path.read_bytes() + (Path(str(path) + "-wal").read_bytes() if Path(str(path) + "-wal").exists() else b"")
    assert canary.encode() not in data
    store.close()


def test_backup_copies_rows_still_in_the_wal(tmp_path, fixed_library):
    store = Store(tmp_path / "leafi.db")
    store.insert("books", title="In the WAL", language="en", created_at=now_iso())
    dest = store.backup(tmp_path / "backups" / "copy.db")
    copy = sqlite3.connect(str(dest))
    assert copy.execute("SELECT title FROM books").fetchall() == [("In the WAL",)]
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copy.close()
    store.close()


def test_backup_command_writes_a_timestamped_copy(tmp_path, settings, monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    with Store(settings.db_path) as store:
        store.insert("books", title="B", language="en", created_at=now_iso())
    assert cli.main(["backup"]) == 0
    made = list((settings.data_dir / "backups").glob("leafi-*.db"))
    assert len(made) == 1
    assert str(made[0]) in capsys.readouterr().out
    assert cli.main(["forget", "--session", "1"]) == 0  # forgetting never edits a backup, and says so
    assert "1 backup(s)" in capsys.readouterr().out


def test_leafi_miscue_status_and_reason_enums_are_enforced(tmp_path):
    import sqlite3

    store = Store(tmp_path / "leafi.db")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert("knowledge_items", kind="flashcard", language="en", key="x", anki_item_key="k",
                     created_at=now_iso(), updated_at=now_iso())


def test_close_stale_sessions(tmp_path):
    """A crashed session (ended_at null) is closed on the next start: open candidates → unsure(interrupted),
    tokens settled, reading state kept, summary.interrupted = true (ADR-0013 → Interrupted session)."""
    from leafi.core.storage import dumps, loads
    from leafi.study import records
    from leafi.study.alignment import ReadingState, align
    from tests import seed

    store = Store(tmp_path / "leafi.db")
    text = "The dog ran far."
    book, page, rev = seed.book_page(store, text, source="manual")
    sid = seed.session(store, book)
    read = seed.page_read(store, sid, page, rev)
    st, _, _ = align(ReadingState.from_text(text), ["The", "dog", "red"], 1)
    store.execute("UPDATE page_reads SET reading_state=? WHERE id=?", (dumps(st.to_json()), read))
    mid = seed.miscue(store, read, rev, text, "ran")
    assert records.close_stale_sessions(store) == [sid]
    assert seed.status_of(store, mid) == ("unsure", "interrupted")
    s = store.one("SELECT * FROM reading_sessions WHERE id=?", (sid,))
    assert s["ended_at"] is not None and loads(s["summary"])["interrupted"] is True
    kept = ReadingState.from_json(text, loads(store.one("SELECT reading_state FROM page_reads")["reading_state"]))
    assert kept.statuses() == "P P S U" and (kept.pcur, kept.ccur) == (3, 3)
    assert records.close_stale_sessions(store) == []
