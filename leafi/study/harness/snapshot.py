"""The session panel's view of a running session (session panel design D3): synchronous, memory only, values only.

It runs on the session's loop thread (the panel device calls it there and publishes the result), reads no database
and lets no object escape: every field is a copy, ready for JSON. It restates no rule; the reading counts are
`world.reading_counts`, the statuses ADR-0013's.
"""

from __future__ import annotations

import math
import time

from leafi.study.harness.inputs import EYE_OFFLINE_AFTER
from leafi.study.harness.state import Session
from leafi.study.harness.world import World, reading_counts


def _left(deadline: float, now: float) -> float | None:
    return None if math.isinf(deadline) else round(deadline - now, 1)


def _entry(e: dict) -> dict:
    out = {k: v for k, v in e.items() if k != "progress"}
    out["params"] = dict(e.get("params") or {})
    out["progress"] = dict(e.get("progress") or {})
    return out


def _want(s: Session, w: World) -> dict | None:
    want, io = s.latch.want, w.inputs
    if want is None:
        return None
    if not s.log and not s.boundary.menu:
        waiting = "setup"  # before the first boundary: it waits for name and book
    elif io._waiting > 0:
        waiting = "brain"  # first: the filler may be speaking during a Brain wait
    elif io.speaking:
        waiting = "speech"
    else:
        waiting = "step"
    return {"kind": want.kind, "source": want.source, "age_s": round(time.monotonic() - want.at, 1),
            "waiting_for": waiting}


def _reading(w: World) -> dict | None:
    st = w.state
    if st is None:
        return None
    cur = st.current_sentence()
    return {"page_read_id": w.read_id, "sentences": {"completed": len(st.completed), "total": len(st.sentence_ids())},
            "tokens": reading_counts(st),
            "current_sentence": [{"text": t.text, "status": t.status} for t in st.tokens if t.sentence_id == cur]
            if cur is not None else []}


def snapshot(s: Session, w: World) -> dict:
    now, io, b = time.monotonic(), w.inputs, s.boundary
    running = next((e for e in reversed(s.log) if e["status"] == "running"), None)
    return {
        "session": {"id": s.session_id, "arm": s.arm, "terminal": s.latch.terminal,
                    "elapsed_s": round(now - s.ledger.started, 1), "soft_left_s": _left(s.soft_deadline, now),
                    "hard_left_s": _left(s.latch.hard_deadline, now)},
        "learner": dict(s.learner_label),
        "book": {"id": w.book_id, "title": w.book_title},
        "page": {"id": w.page_id, "printed": w.printed, "revision_id": w.rev.id if w.rev else None},
        "activity": _entry(running) if running else None,
        "prompt": {"owner": None if io.current_owner is None else str(io.current_owner), "last_line": io.last_line},
        "io": {"voice": io.voice, "speaking": io.speaking, "listening": io.listening,
               "eye_online": io.eye_misses < EYE_OFFLINE_AFTER, "lease_held": io.lease_held(),
               "accepting": io.accepting},
        "reading": _reading(w),
        "boundary": {"menu": sorted(b.menu), "offer": b.current.kind if b.current else None,
                     "excluded": sorted(b.excluded), "offers": b.offers},
        "want": _want(s, w),
        "activities": [_entry(e) for e in s.log],
        "panel_log": [dict(e) for e in io.panel_log],
    }
