"""Whole-session runs on the harness loop: real Store, scripted console, nothing speaks."""

from __future__ import annotations

import anyio

from leafi.core.hub import Hub
from leafi.core.storage import Store, loads
from leafi.study.harness import loop
from tests.fakes import RecordingFace, ScriptedListener

PAGE = "The fox ran home. It was late and dark."


def env(settings, script, *, page=PAGE, learner=None, listener=None, title="Fixture", **kw) -> loop.Env:
    listener = listener or ScriptedListener(script)
    face = RecordingFace()
    hub = Hub(faces={"f": face}, policy="none", listeners={"console": listener})
    e = loop.Env(store=Store(settings.db_path), hub=hub, settings=settings, listener=listener, book_title=title,
                 page_text=page, page_number=1 if page else None, learner=learner, **kw)
    e.face = face
    return e


async def run(e: loop.Env, limit_s: float = 20) -> int:
    with anyio.fail_after(limit_s):
        return await loop.run_session(e)


def activities(store: Store, sid: int) -> list[tuple]:
    return [(r["kind"], r["status"], bool(r["continuation"])) for r in
            store.all("SELECT kind, status, continuation FROM activities WHERE session_id=? ORDER BY id", (sid,))]


def summary(store: Store, sid: int) -> dict:
    return loads(store.one("SELECT summary FROM reading_sessions WHERE id=?", (sid,))["summary"], {})
