"""Builders for harness tests: a real Store, a scripted Talk, configurable Facts."""

from __future__ import annotations

import time
from dataclasses import replace

from leafi.core.storage import Store
from leafi.core.text import typed_utterance
from leafi.study.harness import settings as hs
from leafi.study.harness.latch import Latch
from leafi.study.harness.ledger import Ledger
from leafi.study.harness.state import Facts, Session
from tests import seed


class ScriptedTalk:
    """Answers each listen() with the next scripted reply (None = silence, "SKIP" = a skip control posted to the
    latch as the input layer does, then the utterance "skip"). Records every line said."""

    def __init__(self, replies, latch: Latch | None = None) -> None:
        self.replies = list(replies)
        self.said: list[str] = []
        self.books: list[bool] = []  # each line's book flag (ADR-0021 E2)
        self.listens = 0
        self.latch = latch

    async def say(self, text: str, **kw) -> None:
        self.said.append(text)
        self.books.append(kw.get("book", False))

    async def ask(self, owner, text: str, **kw) -> None:  # M7 design D21: a prompt, recorded like a line
        self.said.append(text)
        self.books.append(kw.get("book", False))

    async def listen(self, timeout_s, owner=None, *, accepts_page=True):
        self.listens += 1
        r = self.replies.pop(0) if self.replies else None
        if r is None:
            return None
        if r == "SKIP":
            self.latch.post_skip()
            r = "skip"
        return typed_utterance(r)


def make_session(tmp_path, *, replies=(), facts: Facts | None = None, values: dict | None = None,
                 cycle: bool = False, kind: str = "learner") -> Session:
    store = Store(tmp_path / "leafi.db")
    learner = seed.learner(store) if kind == "learner" else store.insert(
        "learners", kind=kind, display_name="Guest", settings="{}", created_at="2026-10-23T00:00:00+00:00")
    book, _, _ = seed.book_page(store, "The fox ran home.")
    sid = seed.session(store, book, learner_id=learner)
    latch = Latch()
    st = hs.LearnerSettings(values or {}, kind=kind)
    talk = ScriptedTalk(replies, latch)
    s = Session(store=store, latch=latch, ledger=Ledger(store, sid, st.limits()), settings=st, talk=talk,
                session_id=sid, learner_id=learner)
    f = facts or Facts()
    s.facts_fn = lambda _s: f
    if cycle:
        from leafi.study.harness import rows

        aid = rows.start_activity(store, session_id=sid, kind="read_listen", cycle_id=None)
        s.cycle_id = rows.open_cycle(store, sid, aid)
        store.execute("UPDATE activities SET cycle_id=?, status='completed' WHERE id=?", (s.cycle_id, aid))
    return s


def with_facts(s: Session, **kw) -> Session:
    f = replace(s.facts(), **kw)
    s.facts_fn = lambda _s: f
    return s


def past_soft_deadline(s: Session) -> Session:
    s.soft_deadline = time.monotonic() - 1
    return s
