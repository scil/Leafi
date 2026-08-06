import datetime as dt
import sqlite3
from pathlib import Path

DB = Path("data/sessions.db")

_EXTRA_COLS = [
    ("active_seconds", "REAL"),
    ("inside_seconds", "REAL"),
    ("verified", "INTEGER"),
    ("confidence", "REAL"),
]


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS sessions("
        "ts TEXT, date TEXT, task TEXT, status TEXT, "
        "active_seconds REAL, inside_seconds REAL, verified INTEGER, confidence REAL)"
    )
    have = {row[1] for row in con.execute("PRAGMA table_info(sessions)")}
    for col, typ in _EXTRA_COLS:  # 兼容 P0 老库
        if col not in have:
            con.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ}")
    return con


def record(
    task: str,
    status: str,
    active_seconds: float = 0.0,
    inside_seconds: float = 0.0,
    verified: bool | None = None,
    confidence: float | None = None,
    on_date: dt.date | None = None,
) -> None:
    """status: present | present_late | verified | partial | missed"""
    now = dt.datetime.now()
    date = (on_date or now.date()).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
            (now.isoformat(timespec="seconds"), date, task, status,
             active_seconds, inside_seconds,
             None if verified is None else int(verified), confidence),
        )


def save(task: str, status: str) -> None:  # P0 兼容别名
    record(task, status)


def _day_statuses(con: sqlite3.Connection, date: str) -> list[str]:
    return [s for (s,) in con.execute("SELECT status FROM sessions WHERE date=?", (date,))]


def streak_days(today: dt.date | None = None) -> int:
    """连击天数:从今天(今天还没记录则从昨天)往回数,当天有记录且无 missed 记 1 天。"""
    today = today or dt.date.today()
    with _conn() as con:
        day = today
        if not _day_statuses(con, day.isoformat()):
            day -= dt.timedelta(days=1)
        streak = 0
        while True:
            statuses = _day_statuses(con, day.isoformat())
            if not statuses or "missed" in statuses:
                break
            streak += 1
            day -= dt.timedelta(days=1)
        return streak


def week_stats(today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=6)).isoformat()
    with _conn() as con:
        rows = list(con.execute("SELECT status FROM sessions WHERE date>=?", (since,)))
    done = sum(1 for (s,) in rows if s != "missed")
    return {"done": done, "missed": len(rows) - done, "total": len(rows)}


def week_by_task(today: dt.date | None = None) -> dict[str, tuple[int, int]]:
    """近 7 天分任务统计:{task: (完成次数, 未完成次数)}"""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=6)).isoformat()
    out: dict[str, tuple[int, int]] = {}
    with _conn() as con:
        for task, status in con.execute(
            "SELECT task, status FROM sessions WHERE date>=? ORDER BY task", (since,)
        ):
            done, missed = out.get(task, (0, 0))
            if status == "missed":
                missed += 1
            else:
                done += 1
            out[task] = (done, missed)
    return out
