import datetime as dt

import agent.storage as storage
from agent.config import Settings
from agent.report import build_report


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB", tmp_path / "t.db")
    today = dt.date(2026, 8, 9)  # 周日
    for d in range(1, 6):
        storage.record("brush_pm", "verified", on_date=today - dt.timedelta(days=d))
    storage.record("water", "present", on_date=today - dt.timedelta(days=1))
    storage.record("brush_am", "missed", on_date=today - dt.timedelta(days=2))
    return today


def test_build_report(tmp_path, monkeypatch):
    today = _seed(tmp_path, monkeypatch)
    text = build_report(today=today)
    assert "完成 6 次" in text and "漏掉 1 次" in text
    assert "晚刷牙:完成 5 次" in text
    assert "早刷牙" in text and "未完成 1 次" in text
    assert "零漏打卡" not in text  # 有 missed 就不该表扬


def test_build_report_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB", tmp_path / "t.db")
    assert "还没有任何打卡记录" in build_report()


def test_week_by_task(tmp_path, monkeypatch):
    today = _seed(tmp_path, monkeypatch)
    by = storage.week_by_task(today=today)
    assert by["brush_pm"] == (5, 0)
    assert by["brush_am"] == (0, 1)
    assert by["water"] == (1, 0)


def test_parsed_weekly_report():
    assert Settings(weekly_report="sun:20:45").parsed_weekly_report() == ("sun", 20, 45)
    assert Settings(weekly_report=" ").parsed_weekly_report() is None
