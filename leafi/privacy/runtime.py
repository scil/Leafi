"""The process's egress and who the current work is attributed to (M5 design D5).

`get(settings)` returns the one `Egress` of this process, built on first need (after `leafi.bootstrap`). A
service that sends calls it rather than having an Egress threaded through every constructor; tests install their
own with `use(...)`.

`attribution` is the learner and session an outbound request is recorded against when its caller does not name
them (a TTS line, a book lookup): the harness sets it at session start to the session's guest row and moves it
to the learner at adoption, so a study purpose always has a learner and nothing is sent unattributed.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from leafi.core.config import Settings


@dataclass
class Attribution:
    """Mutable on purpose: adoption moves it to the learner, and every task that copied the context (the
    session's children, the post-session steps) sees the move."""

    learner_id: int
    session_id: int | None = None


attribution: contextvars.ContextVar[Attribution | None] = contextvars.ContextVar("leafi_attribution", default=None)

_lock = threading.Lock()
_egress = None


def get(settings: Settings):
    """The process's Egress (built once; `leafi.privacy.egress` is imported only when something sends)."""
    global _egress
    with _lock:
        if _egress is None:
            from leafi.privacy.egress import Egress

            _egress = Egress(settings)
        return _egress


def use(egress) -> None:
    """Install (or, with None, drop) the process's Egress: tests and the composition root."""
    global _egress
    with _lock:
        if _egress is not None and egress is not _egress:
            _egress.close()
        _egress = egress


@contextmanager
def attributed(learner_id: int, session_id: int | None = None) -> Iterator[None]:
    token = attribution.set(Attribution(learner_id, session_id))
    try:
        yield
    finally:
        attribution.reset(token)


def attribute(learner_id: int, session_id: int | None = None) -> None:
    """Move the current attribution (adoption: guest → learner) for every context sharing it."""
    cur = attribution.get()
    if cur is None:
        attribution.set(Attribution(learner_id, session_id))
        return
    cur.learner_id = learner_id
    if session_id is not None:
        cur.session_id = session_id
