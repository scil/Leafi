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


def test_leafi_miscue_status_and_reason_enums_are_enforced(tmp_path):
    import sqlite3

    store = Store(tmp_path / "leafi.db")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert("knowledge_items", kind="flashcard", language="en", key="x", anki_item_key="k",
                     created_at=now_iso(), updated_at=now_iso())
