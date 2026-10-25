"""The observation sent to `decide` (ADR-0017 §4; M7 design D3, D6, D12, D15): sections in the one rendering order,
every piece a `Leaf` (book fields marked, ADR-0021 E2), rendered ids for everything the Brain may cite.

Order, stable first (D6): `page`, `memory`, `cycle`, `menu`, then the volatile `last_activity`, `session`, `turn`.
A learner's heard word is a non-book leaf: egress redacts it by content like every text (ADR-0021 E1; the
provenance and substitute it once carried are gone, E6). Ids are rendered (`s<page_read>.<sentence>`,
`m<miscue>`, `i<item>`, `a<activity>`) and `ids` maps them back, so a decision can only cite what this
observation showed (D15). The turn is an opaque counter, never a
session or learner id (D12).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from leafi.core.ports import Leaf, Section


@dataclass(frozen=True)
class Candidate:
    miscue_id: int
    expected: str
    heard: str | None
    origin: str  # substitution | deletion | supplied
    learner_id: int


@dataclass(frozen=True)
class Item:
    item_id: int
    key: str
    kind: str


@dataclass(frozen=True)
class ObservationInput:
    page_read_id: int | None = None
    sentences: tuple[tuple[int, str], ...] = ()  # (sentence id, text) of the current page read
    unread_from: int | None = None
    difficulties: tuple[tuple[str, float], ...] = ()  # (expected word, weight), the learner's, high first
    candidates: tuple[Candidate, ...] = ()
    new_items: tuple[Item, ...] = ()
    recall_due: tuple[Item, ...] = ()
    cardable: tuple[Item, ...] = ()
    menu: tuple[str, ...] = ()
    default_chain: tuple[str, ...] = ()
    last_activity: dict | None = None  # kind, status, counts: Leafi's own record, no text
    session: dict = field(default_factory=dict)  # elapsed, remainders, autonomy: numbers
    turn: int = 0


@dataclass
class Observation:
    sections: tuple[Section, ...]
    ids: dict[str, tuple[str, int]]  # rendered id -> (kind, db id)
    turn: str


def observe(o: ObservationInput) -> Observation:
    ids: dict[str, tuple[str, int]] = {}

    def item_leaf(it: Item) -> Leaf:
        rid = f"i{it.item_id}"
        ids[rid] = ("item", it.item_id)
        return Leaf(f"{rid} {it.kind} '{it.key}'", book=True)  # item keys come from the page

    page = []
    for sid, text in o.sentences:
        rid = f"s{o.page_read_id}.{sid}"
        ids[rid] = ("sentence", sid)
        page.append(Leaf(f"{rid}: {text}", book=True))
    if o.unread_from is not None:
        page.append(Leaf(f"unread from s{o.page_read_id}.{o.unread_from}"))
    memory = [Leaf(f"difficulty '{w}' {weight:.1f}", book=True) for w, weight in o.difficulties[:10]]
    cycle = []
    for c in o.candidates:
        rid = f"m{c.miscue_id}"
        ids[rid] = ("candidate", c.miscue_id)
        cycle.append(Leaf(f"{rid} expected '{c.expected}' {c.origin}", book=True))
        if c.heard:
            cycle.append(Leaf(f"{rid} heard '{c.heard}'"))
    cycle += [item_leaf(it) for it in o.new_items]
    if o.recall_due:
        cycle.append(Leaf("recall due:"))
        cycle += [item_leaf(it) for it in o.recall_due]
    if o.cardable:
        cycle.append(Leaf("cardable:"))
        cycle += [item_leaf(it) for it in o.cardable]
    menu = [Leaf("allowed: " + ", ".join(o.menu)), Leaf("default chain: " + ", ".join(o.default_chain))]
    last = []
    if o.last_activity:
        aid = o.last_activity.get("id")
        if aid is not None:
            ids[f"a{aid}"] = ("activity", int(aid))
        last.append(Leaf(", ".join(f"{k}={v}" for k, v in sorted(o.last_activity.items())
                                   if k != "id") + (f" (a{aid})" if aid is not None else "")))
    session = [Leaf(", ".join(f"{k}={v}" for k, v in sorted(o.session.items())))] if o.session else []
    turn = f"t{o.turn}"
    sections = tuple(Section(name, tuple(leaves)) for name, leaves in (
        ("page", page), ("memory", memory), ("cycle", cycle), ("menu", menu), ("last_activity", last),
        ("session", session), ("turn", [Leaf(turn)])) if leaves)
    return Observation(sections, ids, turn)
