"""A World for activity tests: real Store and Inputs, a scripted console, nothing speaks."""

from __future__ import annotations

import anyio

from leafi.core.hub import Hub
from leafi.core.storage import Store
from leafi.study import books
from leafi.study.harness import activities, rows
from leafi.study.harness import settings as hs
from leafi.study.harness.inputs import Inputs
from leafi.study.harness.latch import Latch, Terminal
from leafi.study.harness.ledger import Ledger
from leafi.study.harness.state import Activity, Session
from leafi.study.harness.world import PageRequest, World
from tests import seed
from tests.fakes import RecordingFace, ScriptedListener

PAGE_1 = "The fox ran home. It was late and dark."
PAGE_2 = "The moon was up. The fox slept."


def make_world(tmp_path, settings, script, *, page=PAGE_1, number=1, values=None, anki=None, listener=None,
               word_info=None) -> World:
    store = Store(settings.db_path)
    learner = seed.learner(store)
    book = books.find_or_create(store, "Fixture")
    sid = seed.session(store, book, learner_id=learner)
    latch = Latch()
    lst = hs.LearnerSettings(values or {})
    listener = listener or ScriptedListener(script)
    face = RecordingFace()
    hub = Hub(faces={"f": face}, policy="none", listeners={"console": listener})
    inputs = Inputs(hub=hub, latch=latch, store=store, listener=listener)
    s = Session(store=store, latch=latch, ledger=Ledger(store, sid, lst.limits()), settings=lst, talk=inputs,
                session_id=sid, learner_id=learner)
    w = World(s=s, inputs=inputs, settings=settings, book_id=book, anki=anki, word_info=word_info,
              page_request=PageRequest(number, page) if page is not None else None)
    s.facts_fn = w.facts
    w.face = face
    return w


async def run(w: World, kind: str, params: dict | None = None, *, continuation: bool = False, **activity):
    """`activity`: further `Activity` fields (Brain content: `content`, `content_owner`, `content_provenance`)."""
    params = dict(params or {})
    if continuation:
        params["continuation"] = True
    store, s = w.store, w.s
    aid = rows.start_activity(store, session_id=s.session_id, kind=kind, cycle_id=s.cycle_id,
                              continuation=continuation)
    result = None
    latch = s.latch
    try:
        with anyio.CancelScope() as latch.scope:
            async with anyio.create_task_group() as latch.tg:
                w.inputs.start()
                try:
                    with anyio.fail_after(10):
                        result = await activities.KINDS[kind](w, Activity(kind, params, "default", **activity), aid)
                finally:
                    latch.tg.cancel_scope.cancel()
    except* Terminal:
        pass
    status, outcome = result if result else (latch.status(), {})
    rows.finish_activity(store, aid, status, outcome, learner_id=s.learner_id)
    return status, outcome, aid


def candidates(w: World) -> dict[str, tuple]:
    return {r["expected"]: (r["status"], r["unsure_reason"] or r["withdrawn_reason"], r["cycle_id"])
            for r in w.store.all("SELECT * FROM miscues ORDER BY id")}
