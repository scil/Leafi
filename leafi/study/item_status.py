"""An item's status as a fold over its evidence (ADR-0017 §6.2; M7 design D17).

`knowledge_items.status` is a cache: `apply` is its only writer, and it recomputes the status from the item's
`retrieval_events` and `item_status_events` with `fold`, which is pure and total (every history, the empty one
included, has exactly one result, decided by the first rule that applies):

1. ignored: the latest `ignore` / `unignore` is an `ignore`;
2. follows a card: a card id whose latest event is not `card_gone` — `known` at `ivl_days` ≥ the threshold, `lapsed`
   when an earlier state of the same card was there and `lapses` grew since, else `learning`;
3. new: no retrieval event;
4. retrievals: `mastery.mode = anki` → `learning`; `retrievals` → `known` after `min_retrievals` successes over
   `min_days` household days since the last reset, `lapsed` on a fail while known (the count resets);
5. the next recall day (rule 4's `learning` and `lapsed` only): 1 day after the first event, each success one step
   along 1 → 2 → 4 days from its own day, a fail back to 1 day.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from leafi.core import learner_store
from leafi.core.storage import Store, now_iso

log = logging.getLogger("leafi.item_status")

RECALL_STEPS_DAYS = (1, 2, 4)  # ADR-0017 §6.2, untuned
EVENTS = ("ignore", "unignore", "card_ack", "card_state", "card_gone")


def household_day(tz: str = "", when: dt.datetime | None = None) -> str:
    """The household's date (`HOUSEHOLD_TZ`, an IANA name; empty: this machine's zone) of `when` (default now)."""
    when = when or dt.datetime.now(dt.UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return (when.astimezone(ZoneInfo(tz)) if tz else when.astimezone()).date().isoformat()


def ivl_days(ivl: int | float) -> float:
    """Anki's interval: days when ≥ 0, a duration in seconds when negative (learning steps)."""
    return float(ivl) if ivl >= 0 else -float(ivl) / 86400


@dataclass(frozen=True)
class Retrieval:
    at: str
    id: int
    day: str
    outcome: str  # success | fail


@dataclass(frozen=True)
class Event:
    at: str
    id: int
    event: str
    card_id: int | None = None
    ivl_days: float | None = None
    lapses: int | None = None


@dataclass(frozen=True)
class Mastery:
    mode: str = "retrievals"  # retrievals | anki
    min_retrievals: int = 6
    min_days: int = 3
    known_days: float = 21  # REVIEW_KNOWN_INTERVAL_DAYS


def _plus(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def _card_status(events: list[Event], known: float) -> str | None:
    by_card: dict[int, list[Event]] = {}
    for e in events:
        if e.event in ("card_ack", "card_state", "card_gone") and e.card_id is not None:
            by_card.setdefault(e.card_id, []).append(e)
    live = [evs for evs in by_card.values() if evs[-1].event != "card_gone"]
    if not live:
        return None
    card = max(live, key=lambda evs: (evs[-1].at, evs[-1].id))
    states = [e for e in card if e.event == "card_state" and e.ivl_days is not None]
    if not states:
        return "learning"
    last = states[-1]
    if last.ivl_days >= known:
        return "known"
    if any(s.ivl_days >= known and (last.lapses or 0) > (s.lapses or 0) for s in states[:-1]):
        return "lapsed"
    return "learning"


def fold(retrievals: list[Retrieval], events: list[Event], m: Mastery = Mastery()) -> tuple[str, str | None]:
    """(status, next recall day or None); both lists in any order."""
    retrievals = sorted(retrievals, key=lambda r: (r.at, r.id))
    events = sorted(events, key=lambda e: (e.at, e.id))
    marks = [e for e in events if e.event in ("ignore", "unignore")]
    if marks and marks[-1].event == "ignore":
        return "ignored", None
    card = _card_status(events, m.known_days)
    if card is not None:
        return card, None
    if not retrievals:
        return "new", None
    status = "learning"
    if m.mode == "retrievals":
        successes, days = 0, set()
        for r in retrievals:
            if r.outcome == "fail":
                if status == "known":
                    status, successes, days = "lapsed", 0, set()
                continue
            successes += 1
            days.add(r.day)
            if status != "known" and successes >= m.min_retrievals and len(days) >= m.min_days:
                status = "known"
    if status == "known":
        return status, None
    step = 0
    due = _plus(retrievals[0].day, RECALL_STEPS_DAYS[0])
    for r in retrievals[1:]:
        step = min(step + 1, len(RECALL_STEPS_DAYS) - 1) if r.outcome == "success" else 0
        due = _plus(r.day, RECALL_STEPS_DAYS[step])
    return status, due


def mastery_of(store: Store, learner_id: int, known_days: float = 21) -> Mastery:
    from leafi.study.harness import settings as learner_settings

    ls = learner_settings.load(store, learner_id)
    return Mastery(ls["mastery.mode"], int(ls["mastery.min_retrievals"]), int(ls["mastery.min_days"]), known_days)


def evidence(store: Store, item_id: int) -> tuple[list[Retrieval], list[Event]]:
    rs = [Retrieval(r["at"], r["id"], r["day"], r["outcome"]) for r in store.all(
        "SELECT id, at, day, outcome FROM retrieval_events WHERE item_id=?", (item_id,))]
    es = [Event(r["at"], r["id"], r["event"], r["card_id"], r["ivl_days"], r["lapses"]) for r in store.all(
        "SELECT id, at, event, card_id, ivl_days, lapses FROM item_status_events WHERE item_id=?", (item_id,))]
    return rs, es


def apply(store: Store, item_id: int, known_days: float = 21, mastery: Mastery | None = None) -> str | None:
    """Fold the item's evidence and write the cached status when it changed; the only status writer. Runs in the
    caller's transaction. None when the item no longer exists."""
    row = store.one("SELECT learner_id, status FROM knowledge_items WHERE id=?", (item_id,))
    if row is None:
        return None
    m = mastery or mastery_of(store, row["learner_id"], known_days)
    status, _ = fold(*evidence(store, item_id), m)
    if status != row["status"]:
        store.execute("UPDATE knowledge_items SET status=?, updated_at=? WHERE id=?", (status, now_iso(), item_id))
    return status


def apply_all(store: Store, known_days: float = 21) -> int:
    """Re-fold every item (after migration 8, which cannot run the fold from `leafi.core`); the count changed."""
    changed = 0
    masteries: dict[int, Mastery] = {}
    with store.transaction():
        for r in store.all("SELECT id, learner_id, status FROM knowledge_items"):
            m = masteries.setdefault(r["learner_id"], mastery_of(store, r["learner_id"], known_days))
            changed += apply(store, r["id"], known_days, m) != r["status"]
    return changed


def recall_due(store: Store, learner_id: int, today: str, known_days: float = 21) -> list[int]:
    """Item ids in `learning` or `lapsed` with no live card whose next recall day is today or earlier, earliest
    first (ADR-0017 §6.2; the `recall_items` selection)."""
    m = mastery_of(store, learner_id, known_days)
    due = []
    for r in store.all("SELECT DISTINCT k.id FROM knowledge_items k JOIN retrieval_events e ON e.item_id = k.id "
                       "WHERE k.learner_id=? AND k.status IN ('learning','lapsed')", (learner_id,)):
        status, day = fold(*evidence(store, r["id"]), m)
        if day is not None and day <= today:
            due.append((day, r["id"]))
    return [i for _, i in sorted(due)]


def record(store: Store, learner_id: int, item_id: int, event: str, source: str, *, tz: str = "",
           known_days: float = 21, session_id: int | None = None, activity_id: int | None = None,
           card_id: int | None = None, ivl: float | None = None, lapses: int | None = None,
           revlog_id: int | None = None, revlog_type: int | None = None) -> str | None:
    """Append one evidence row through the owner fence and re-fold the item, in one transaction. Raises
    `LearnerUnavailable` when the learner is being forgotten (the caller drops the row, M7 design D22)."""
    if event not in EVENTS:
        raise ValueError(f"{event}: one of {', '.join(EVENTS)}")
    at = now_iso()
    with store.transaction():
        learner_store.insert(store, "item_status_events", learner_id, item_id=item_id, at=at,
                             day=household_day(tz), event=event, source=source, session_id=session_id,
                             activity_id=activity_id, card_id=card_id, ivl_days=ivl, lapses=lapses,
                             revlog_id=revlog_id, revlog_type=revlog_type)
        return apply(store, item_id, known_days)


def latest_card_events(store: Store, learner_id: int) -> dict[int, dict]:
    """card id → its latest event row for the learner (for `anki.observe_cards`' change test)."""
    out: dict[int, dict] = {}
    for r in store.all("SELECT * FROM item_status_events WHERE learner_id=? AND card_id IS NOT NULL ORDER BY at, id",
                       (learner_id,)):
        out[r["card_id"]] = dict(r)
    return out


def latest_card_states(store: Store, learner_id: int) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in store.all("SELECT * FROM item_status_events WHERE learner_id=? AND event='card_state' "
                       "ORDER BY at, id", (learner_id,)):
        out[r["card_id"]] = dict(r)
    return out
