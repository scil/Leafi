"""Provenance of a text (ADR-0018 §3; M7 design D2). Import-free, so every layer can use it.

A text has a class — `system` (Leafi's own phrase), `page`, `parent`, `learner` (a learner's own words) or
`derived_from_learner` — and the learners it came from. The output of a Brain call carries every restriction of
what it was given (`of_output`): a single "strongest class" could not hold two independent permissions (a
learner's `cloud.text` and the household's CLOUD_PARENT_TEXT), so a mixed output keeps its learner sources and adds
`PARENT_SOURCE`, a reserved id that names no learner and means "parent text went into this".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

PARENT_SOURCE = 0  # learner ids start at 1; every reader of sources treats 0 as a flag, never as a learner
LEARNER_CLASSES = ("learner", "derived_from_learner")


@dataclass(frozen=True)
class Provenance:
    """Where a spoken or sent text came from, and the learners it came from. The TTS service routes by it."""

    cls: str = "system"
    sources: tuple[int, ...] = ()

    @property
    def learners_own(self) -> bool:
        return self.cls in LEARNER_CLASSES

    @property
    def learner_sources(self) -> tuple[int, ...]:
        return tuple(s for s in self.sources if s != PARENT_SOURCE)

    @property
    def parent_origin(self) -> bool:
        return PARENT_SOURCE in self.sources


SYSTEM = Provenance()


@dataclass(frozen=True)
class Leaf:
    """One piece of text with its provenance, as the Brain port carries it (M7 design D3/D5); a backend turns it
    into `leafi.privacy.egress.Text` when it prepares the request."""

    value: str
    prov: Provenance = SYSTEM


def of_output(sent: Iterable[Provenance]) -> Provenance:
    """The provenance of a Brain output from the provenance of every leaf actually sent to that backend: never
    weaker than `derived_from_learner` when any sent leaf came from a learner (a model output quoting a learner is
    not the learner's words, yet derives from them); parent origin kept as `PARENT_SOURCE` beside them."""
    sent = list(sent)
    classes = {p.cls for p in sent}
    learners = sorted({s for p in sent for s in p.learner_sources})
    if classes & set(LEARNER_CLASSES):
        parent = any(p.cls == "parent" or p.parent_origin for p in sent)
        return Provenance("derived_from_learner", tuple(([PARENT_SOURCE] if parent else []) + learners))
    for cls in ("parent", "page"):
        if cls in classes:
            return Provenance(cls)
    return SYSTEM
