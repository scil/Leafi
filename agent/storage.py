import datetime as dt
import sqlite3
from pathlib import Path

DB = Path("data/sessions.db")


def save(task: str, status: str) -> None:
    """status: present | present_late | missed(P1 起加 active_seconds / verified 等列)"""
    DB.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS sessions(ts TEXT, date TEXT, task TEXT, status TEXT)"
        )
        now = dt.datetime.now()
        con.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            (now.isoformat(timespec="seconds"), now.date().isoformat(), task, status),
        )
