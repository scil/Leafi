"""Session state shared by the loop, the menu, construction and negotiation (ADR-0017 §1-§3).

`Facts` are what `allowed(s)` and the default policy's `when` words read; the activities compute them from the
store and the devices (`facts_fn`), so the decision code stays pure and testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from leafi.core.ports import SYSTEM, Provenance, Utterance
from leafi.core.storage import Store
from leafi.study.harness.latch import Latch
from leafi.study.harness.ledger import Ledger
from leafi.study.harness.settings import LearnerSettings


class Talk(Protocol):
    async def say(self, text: str, *, provenance: Provenance = SYSTEM,
                  epoch: tuple | None = None) -> None: ...  # M5 design D13; M7 D12: dropped under a newer epoch
    async def ask(self, owner, text: str, *, provenance: Provenance = SYSTEM,
                  epoch: tuple | None = None) -> None: ...  # M7 D21: a prompt
    async def listen(self, timeout_s: float | None, owner=..., *, accepts_page: bool = True
                     ) -> Utterance | None: ...


@dataclass(frozen=True)
class Facts:
    first_boundary: bool = True
    anki_reachable: bool = False
    anki_due: int = 0
    reviews_goal_met: bool = False
    has_book: bool = False
    unread_current: bool = False          # the current page read has an unread range
    can_acquire_next_page: bool = False
    familiar_pages: bool = False
    recall_due: tuple[int, ...] = ()      # item ids
    open_candidates: tuple[int, ...] = ()  # miscue ids of the open cycle, by Difficulty weight then position
    new_item_candidates: tuple[int, ...] = ()
    read_sentences: bool = False          # the open cycle has read sentences
    cardable_items: tuple[int, ...] = ()


@dataclass(frozen=True)
class Spec:
    """A proposed activity: selection fields from any sequencer, content fields only from the content owner."""

    kind: str
    params: dict = field(default_factory=dict)
    content: dict | None = None
    source: str = "default"  # brain | default | learner


@dataclass(frozen=True)
class Activity:
    kind: str
    params: dict
    decided_by: str
    content: dict | None = None
    content_owner: str = "code"
    override: str | None = None
    content_provenance: Provenance = SYSTEM  # M7 D15: what the content's writers store and its lines carry
    degraded: bool = False                   # M7 D10: the content came from a weaker tier than its route's


@dataclass(frozen=True)
class Rejected:
    reason: str


@dataclass
class Boundary:
    """Per-boundary negotiation state; survives Reobserve, cleared when an activity starts (§2.1)."""

    excluded: set[str] = field(default_factory=set)
    wanted: str | None = None
    current: Activity | None = None
    reask: bool = False
    offers: int = 0
    silences: int = 0
    override: str | None = None
    content: dict = field(default_factory=dict)  # M7 D14: (kind, selection) -> generated content or Rejected
    content_epoch: tuple | None = None           # the epoch `content` was made under; another epoch clears it
    moment: float | None = None                  # the `next_activity` moment every Brain call here shares


@dataclass
class Session:
    store: Store
    latch: Latch
    ledger: Ledger
    settings: LearnerSettings
    talk: Talk
    session_id: int
    learner_id: int
    facts_fn: Callable[[Session], Facts] = lambda s: Facts()
    arm: str = "default"
    propensity: float | None = None
    cycle_id: int | None = None
    soft_deadline: float = float("inf")  # time.monotonic() clock
    boundary: Boundary = field(default_factory=Boundary)
    previous_boundary_was_wait: bool = False
    brain: Any = None  # M7: the composition root's `Brain` (tiers, routes, backends); None = no Brain content
    mouth: str = "pc"  # M7 D12: the primary Mouth kind the moments are sized for (`pc`, `camera`)
    pending_rows: list = field(default_factory=list)  # §7.3: activity ends a busy store could not take yet
    on_page: Callable[[Utterance], None] | None = None  # D21: a page turn heard at a boundary (the World's)
    pending_audit_brain: list = field(default_factory=list)  # D8: brain_calls rows a busy store kept back

    def facts(self) -> Facts:
        return self.facts_fn(self)

    def epoch(self) -> tuple:
        return self.latch.epoch.key()

    def checkpoint(self) -> None:
        self.latch.checkpoint()

    def take_skip(self) -> bool:
        return self.latch.take_skip()

    @property
    def autonomy(self) -> int:
        return int(self.settings["autonomy"])

    def past_soft_deadline(self) -> bool:
        return time.monotonic() >= self.soft_deadline
