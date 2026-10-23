"""Activity statuses (ADR-0017 §2, §3.1): one enum, the table of which kind may end in which status, `TERMINAL`."""

from __future__ import annotations

from enum import StrEnum


class ActivityStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    LEASE_LOST = "lease_lost"
    LISTENER_LOST_NO_CONSOLE = "listener_lost_no_console"
    TIME_UP_SESSION = "time_up_session"
    INTERNAL_ERROR = "internal_error"
    ABORTED_STALE = "aborted_stale"
    STORE_BUSY = "store_busy"
    SKIPPED = "skipped"
    PAGE_TURNED = "page_turned"
    IDLE_SESSION = "idle_session"
    INTERRUPTED = "interrupted"  # written only by startup recovery


S = ActivityStatus
EVERY_KIND = frozenset({S.COMPLETED, S.STOPPED, S.LEASE_LOST, S.LISTENER_LOST_NO_CONSOLE, S.TIME_UP_SESSION,
                        S.INTERNAL_ERROR, S.ABORTED_STALE, S.STORE_BUSY})
KIND_SPECIFIC: dict[str, frozenset[ActivityStatus]] = {
    "review_anki": frozenset({S.SKIPPED, S.IDLE_SESSION}),
    "read_listen": frozenset({S.PAGE_TURNED, S.SKIPPED, S.IDLE_SESSION}),
    "read_aloud": frozenset({S.SKIPPED}),
    "practise_errors": frozenset({S.PAGE_TURNED, S.SKIPPED}),
    "teach_items": frozenset({S.SKIPPED}),
    "recall_items": frozenset({S.SKIPPED}),
    "quiz": frozenset({S.SKIPPED, S.IDLE_SESSION}),
    "learner_questions": frozenset({S.SKIPPED, S.IDLE_SESSION}),
    "add_cards": frozenset({S.SKIPPED}),
    "break": frozenset({S.SKIPPED}),
    "end": frozenset(),
    "wait": frozenset({S.SKIPPED}),  # harness-internal break of `negotiation.wait_s` (§2.1)
}
KINDS = tuple(KIND_SPECIFIC)
TERMINAL = frozenset({S.STOPPED, S.LEASE_LOST, S.IDLE_SESSION, S.TIME_UP_SESSION, S.LISTENER_LOST_NO_CONSOLE,
                      S.INTERNAL_ERROR})

# `s.terminal` reasons (§1) and the status a cancelled activity ends with (the one mapping function).
REASONS = ("stop", "lease_lost", "time_up_session", "listener_lost_no_console", "idle_session", "internal_error")
REASON_STATUS = {"stop": S.STOPPED, "lease_lost": S.LEASE_LOST, "time_up_session": S.TIME_UP_SESSION,
                 "listener_lost_no_console": S.LISTENER_LOST_NO_CONSOLE, "idle_session": S.IDLE_SESSION,
                 "internal_error": S.INTERNAL_ERROR}


class IllegalStatus(ValueError):
    pass


def allowed(kind: str) -> frozenset[ActivityStatus]:
    if kind not in KIND_SPECIFIC:
        raise IllegalStatus(f"unknown activity kind {kind!r}")
    return EVERY_KIND | KIND_SPECIFIC[kind]


def check(kind: str, status: str) -> ActivityStatus:
    """The status, if `kind` may end in it; IllegalStatus otherwise (a kind ends only in its listed statuses)."""
    st = ActivityStatus(status)
    if st not in allowed(kind):
        raise IllegalStatus(f"{kind} cannot end {st}")
    return st


def for_reason(reason: str | None) -> ActivityStatus:
    """The mapping function: a cancellation with no latch set maps to `internal_error` (a safety net)."""
    return REASON_STATUS.get(reason or "internal_error", S.INTERNAL_ERROR)
