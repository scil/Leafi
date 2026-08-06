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
