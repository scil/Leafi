"""The ledger (ADR-0017 §6.3): cumulative counters per session and per open cycle.

Derived, not stored (plan Decision log 2026-10-23): every counter is read from rows the steps already write in
their own transactions, so it cannot drift from them. Only the tier-weighted Brain charges of this session are
kept in memory (no Brain until M7).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from leafi.core.storage import Store, loads

TIER_COST = {"fast": 0.25, "standard": 1.0, "deep": 3.0}  # §5.1


@dataclass(frozen=True)
class Limits:
    max_errors: int = 5          # practice.max_errors per cycle
    max_new_cycle: int = 3       # practice.max_new per cycle
    max_new_session: int = 8     # practice.max_new per session
    quiz_max: int = 4            # quiz.max_questions per cycle
    cards_max: int = 10          # cards.max per session
    activities_per_cycle: int = 6
    brain_calls: float = 40.0    # limits.brain_calls_per_session, tier-weighted


@dataclass
class Ledger:
    store: Store
    session_id: int
    limits: Limits = field(default_factory=Limits)
    started: float = field(default_factory=time.monotonic)
    brain_spent: float = 0.0

    # ---- session
    def minutes(self) -> float:
        return (time.monotonic() - self.started) / 60.0

    def _outcome_sum(self, kind: str, key: str, cycle_id: int | None = None) -> int:
        sql = "SELECT outcome FROM activities WHERE session_id=? AND kind=?"
        args: tuple = (self.session_id, kind)
        if cycle_id is not None:
            sql += " AND cycle_id=?"
            args += (cycle_id,)
        return sum(int(loads(r["outcome"], {}).get(key, 0)) for r in self.store.all(sql, args))

    def cards_left(self) -> int:
        return max(0, self.limits.cards_max - self._outcome_sum("add_cards", "cards"))

    def new_left_session(self) -> int:
        return max(0, self.limits.max_new_session - self._outcome_sum("teach_items", "items"))

    # ---- cycle
    def cycle_errors_left(self, cycle_id: int) -> int:
        """Candidates of the cycle already practised (any `practices` row) count against `practice.max_errors`."""
        used = self.store.one("SELECT COUNT(DISTINCT m.id) AS n FROM miscues m JOIN practices p ON p.miscue_id = m.id "
                              "WHERE m.cycle_id=?", (cycle_id,))["n"]
        return max(0, self.limits.max_errors - used)

    def cycle_new_left(self, cycle_id: int) -> int:
        return max(0, min(self.limits.max_new_cycle - self._outcome_sum("teach_items", "items", cycle_id),
                          self.new_left_session()))

    def cycle_quiz_left(self, cycle_id: int) -> int:
        return max(0, self.limits.quiz_max - self._outcome_sum("quiz", "questions", cycle_id))

    def boundary_activities(self, cycle_id: int) -> int:
        """Boundary-chosen activities of the cycle; continuations do not count (§3.2)."""
        return self.store.one("SELECT COUNT(*) AS n FROM activities WHERE cycle_id=? AND continuation=0",
                              (cycle_id,))["n"]

    # ---- Brain budget (§5.1)
    def can_afford(self, tier: str) -> bool:
        return self.brain_spent + TIER_COST[tier] <= self.limits.brain_calls

    def charge(self, tier: str) -> None:
        self.brain_spent += TIER_COST[tier]
