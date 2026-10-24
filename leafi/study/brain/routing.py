"""Routing by task type and difficulty (ADR-0017 §5.1; M7 design D8–D10), moments (§5.2) and prices (D11).

`difficulty()` reads local signals; `route()` gives the tiers to try in order, weaker ones after the preferred
cells marked `degraded`; `eligible()` keeps a tier's backends whose effective locality (D1) the purpose allows for
this learner. The default table is ADR-0017 §5.1's with the owner's change of 2026-10-23 (O1): `decide` starts on
`fast`. `BRAIN_ROUTES` may override single cells.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

TIERS_STRONGEST_FIRST = ("deep", "standard", "fast")
TIER_RANK = {"fast": 0, "standard": 1, "deep": 2}
DIFFICULTIES = ("low", "normal", "high")
PURPOSES = ("decide", "generate", "answer", "judge", "word")

ROUTES: dict[str, dict[str, tuple[str, ...]]] = {
    "decide": {"low": ("fast", "standard"), "normal": ("fast", "standard"), "high": ("fast", "standard")},  # O1
    "generate": {"low": ("fast", "standard"), "normal": ("standard", "deep"), "high": ("deep", "standard")},
    "answer": {"low": ("fast", "standard"), "normal": ("standard", "deep"), "high": ("deep", "standard")},
    "judge": {"low": ("standard", "deep"), "normal": ("standard", "deep"), "high": ("standard", "deep")},
    "word": {"low": ("fast", "standard"), "normal": ("fast", "standard"), "high": ("standard", "fast")},
}

# §5.2 (untuned): seconds per call by (purpose, tier) — `decide` per tier, D8 — and per whole call.
PER_CALL_S: dict[str, dict[str, float]] = {
    "decide": {"fast": 2.0, "standard": 3.0, "deep": 4.0},
    "generate": {"fast": 4.0, "standard": 4.0, "deep": 4.0},
    "answer": {"fast": 5.0, "standard": 5.0, "deep": 5.0},
    "judge": {"fast": 2.0, "standard": 2.0, "deep": 2.0},
    "word": {"fast": 1.5, "standard": 1.5, "deep": 1.5},
}
TOTAL_S = {"decide": 5.0, "generate": 8.0, "answer": 10.0, "judge": 4.0, "word": 2.0}
MIN_TIER_S = {"fast": 1.0, "standard": 2.0, "deep": 4.0}  # untuned; measured in M10
SKIP_MARGIN_S = 0.3

# §5.2 moments, PC Mouth / camera Mouth (no Mouth: the PC's), and the output reserve subtracted from each.
MOMENTS = {"next_activity": (6.0, 9.0), "feedback": (3.0, 6.0), "answer": (8.0, 12.0), "react": (1.0, 1.0)}
OUTPUT_RESERVE = {"pc": 1.0, "camera": 3.5}

# Vendor prices per MTok (input, output, cache read), claude-api skill, cached 2026-10-06 (D11).
PRICES = {"claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-sonnet-5-5": (2.00, 10.00, 0.20),
          "claude-opus-5-5": (4.00, 20.00, 0.20)}


def difficulty(purpose: str, *, item_kind: str | None = None, question: str | None = None,
               translation: str | None = None, retry: bool = False) -> str:
    """§5.1's local signals (untuned): grammar or pattern items, long or why/how questions, long translations are
    hard; a word line is easy; a retry after an invalid answer is one step up."""
    if purpose == "word":
        d = "low"
    elif item_kind in ("grammar", "pattern"):
        d = "high"
    elif question is not None and (len(question.split()) > 12
                                   or question.strip().lower().startswith(("why", "how"))):
        d = "high"
    elif translation is not None and len(translation.split()) > 20:
        d = "high"
    else:
        d = "normal"
    if retry and d != "high":
        d = DIFFICULTIES[DIFFICULTIES.index(d) + 1]
    return d


def routes(override: str = "") -> dict[str, dict[str, tuple[str, ...]]]:
    """The routing table with `BRAIN_ROUTES`' single-cell overrides applied (an invalid override is ignored)."""
    table = {p: dict(cells) for p, cells in ROUTES.items()}
    if not override.strip():
        return table
    try:
        given = json.loads(override)
    except ValueError:
        return table
    if not isinstance(given, dict):
        return table
    for purpose, cells in given.items():
        if purpose in table and isinstance(cells, dict):
            for d, tiers in cells.items():
                if d in DIFFICULTIES and isinstance(tiers, list) and tiers and all(t in TIER_RANK for t in tiers):
                    table[purpose][d] = tuple(tiers)
    return table


@dataclass(frozen=True)
class Step:
    tier: str
    degraded: bool


def route(purpose: str, d: str, configured: set[str], table: dict | None = None) -> list[Step]:
    """Preferred → escalation, then every other configured tier strongest first, then weaker ones marked
    `degraded` (a FrugalGPT-style cascade); unconfigured tiers are skipped."""
    cell = (table or ROUTES)[purpose][d]
    preferred = cell[0]
    order = list(cell) + [t for t in TIERS_STRONGEST_FIRST if t not in cell]
    out = []
    for t in order:
        if t in configured and t not in [s.tier for s in out]:
            out.append(Step(t, TIER_RANK[t] < TIER_RANK[preferred] and t not in cell))
    return out


def moment_s(name: str, mouth: str) -> float:
    """Seconds the model work of a moment may take: the moment's budget minus the output reserve."""
    pc, camera = MOMENTS[name]
    budget = camera if mouth == "camera" else pc
    return max(0.0, budget - OUTPUT_RESERVE.get(mouth, OUTPUT_RESERVE["pc"]))


def estimated_cost(model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return round((tokens_in * p[0] + tokens_out * p[1] + tokens_cached * p[2]) / 1_000_000, 6)
