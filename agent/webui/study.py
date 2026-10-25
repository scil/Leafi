"""The Reading tab's server side (session panel design rev 5, D5 and D6).

`status` proxies the live session's panel endpoint (found through `data/run/study-panel-<pid>.json`), or, with no
live session, shows the last session from the database opened read-only (`mode=ro`, closed at once, so a polling tab
never holds the lock `leafi migrate` and `backup` need). `action` maps a button to one line of a fixed table and
forwards it only to the session the page showed; the browser never sees the session's token.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("webui.study")

TIMEOUT_S = 1.5
MAX_ANSWER = 500
SIMPLE = {"skip": "/skip", "stop": "/stop", "next_page": "/next", "yes": "/yes", "no": "/no", "know": "/know"}
EASES = ("again", "hard", "good", "easy")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback: never through a proxy


class Refused(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _run_dir(settings) -> Path:
    return Path(settings.data_dir) / "run"


def _live(settings) -> list[dict]:
    from leafi.devices.panel import live, runtime_files

    return [i for i in runtime_files(_run_dir(settings)) if live(i)]  # the web UI never deletes a file


def _call(info: dict, method: str, path: str, body: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode("utf-8"))
    req.add_header("Authorization", f"Bearer {info['token']}")
    req.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---------------------------------------------------------------- status


def status(settings, since: str | None) -> tuple[int, dict | None]:
    """(200, view) or (204, None). The view's `state`: `live`, `busy` (a live process that did not answer in time:
    the page keeps the last snapshot, without buttons), `none` (the last session from the database) or `db_error`."""
    for info in _live(settings):
        try:
            code, body = _call(info, "GET", "/status" + (f"?since={since}" if since else ""))
        except (OSError, TimeoutError):
            return 200, {"state": "busy", "session_id": info.get("session_id")}
        if code == 204:
            return 204, None
        if code == 200:
            return 200, {"state": "live"} | json.loads(body)
        log.info("panel of session %s refused the token (%s)", info.get("session_id"), code)  # a reused pid
    return 200, last_session(settings)


def last_session(settings) -> dict:
    db = Path(settings.db_path)
    if not db.exists():
        return {"state": "none", "last": None}
    try:
        conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error as e:
        return {"state": "db_error", "error": str(e)}
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT s.id, s.started_at, s.ended_at, s.summary, l.display_name, l.kind "
                           "FROM reading_sessions s LEFT JOIN learners l ON l.id = s.learner_id "
                           "ORDER BY s.id DESC LIMIT 1").fetchone()
        if row is None:
            return {"state": "none", "last": None}
        acts = conn.execute("SELECT kind, status, started_at, outcome FROM activities WHERE session_id=? "
                            "ORDER BY id", (row["id"],)).fetchall()
    except sqlite3.Error as e:
        return {"state": "db_error", "error": str(e)}
    finally:
        conn.close()
    return {"state": "none", "last": {
        "id": row["id"], "started_at": row["started_at"], "ended_at": row["ended_at"],
        "learner": {"kind": row["kind"], "name": row["display_name"]},
        "summary": _loads(row["summary"]),
        "activities": [{"kind": a["kind"], "status": a["status"], "started_at": a["started_at"],
                        "outcome": _loads(a["outcome"])} for a in acts]}}


def _loads(text: str | None) -> dict:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- actions (design D6)


def line_for(settings, body: dict) -> str:
    """The one typed line a button sends; anything outside the table is refused (400)."""
    from leafi.study.harness.status import KINDS

    action, text = body.get("action"), body.get("text")
    if action in SIMPLE:
        return SIMPLE[action]
    if action == "ease" and text in EASES:
        return f"/{text}"
    if action == "do" and text in KINDS and text != "wait":
        return f"/do {text}"
    if action == "answer" and isinstance(text, str):
        t = text.strip()
        if t and len(t) <= MAX_ANSWER and "\r" not in t and "\n" not in t and not t.startswith("/"):
            return f"/say {t}"
    if action == "fix" and isinstance(body.get("old"), str) and isinstance(text, str):
        old, new = body["old"].strip(), text.strip()
        if old and " " not in old and new and "\n" not in new and "\r" not in new and len(new) <= MAX_ANSWER:
            return f"/fix {old} {new}"
    if action == "page" and isinstance(body.get("n"), int) and not isinstance(body["n"], bool) and body["n"] >= 0 \
            and isinstance(text, str) and text.strip():
        return f"/page {body['n']} --text {_page_file(settings, body['n'], text)}"
    raise Refused(400, "not a panel action")


def _page_file(settings, n: int, text: str) -> str:
    """The pasted page, at an absolute path both processes read the same way, one file per paste."""
    folder = (Path(settings.cache_dir) / "panel").resolve()
    path = folder / f"page-{n}-{secrets.token_hex(4)}.txt"
    if " " in str(path):  # `/page N --text` joins the path's words with single spaces
        raise Refused(400, f"the cache folder has a space in its path: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return str(path)


def action(settings, body: dict) -> tuple[int, dict]:
    sid, seen = body.get("session_id"), body.get("seen")
    if not isinstance(sid, int) or isinstance(sid, bool):
        return 400, {"error": "no session id"}
    try:
        line = line_for(settings, body)
    except Refused as e:
        return e.code, {"error": str(e)}
    info = next((i for i in _live(settings) if i.get("session_id") == sid), None)
    if info is None:  # never sent to another (newer) session
        return 409, {"error": "that session has ended"}
    payload = {"session_id": sid, "line": line,
               "seen": seen if isinstance(seen, int | float) and not isinstance(seen, bool) else None}
    try:
        code, _ = _call(info, "POST", "/input", payload)
    except (OSError, TimeoutError):
        return 502, {"error": "the session did not answer"}
    if code == 202:
        return 200, {"ok": True, "line": line}
    if code == 409:
        return 409, {"error": "that session has ended"}
    return (400 if code == 400 else 502), {"error": f"the session refused it ({code})"}
