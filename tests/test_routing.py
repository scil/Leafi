"""Routing (ADR-0017 §5.1, M7 design D9–D10): difficulty signals, the cascade with `degraded`, the owner's
`decide` change (O1), single-cell overrides, moments."""

from __future__ import annotations

from leafi.study.brain import routing as r


def test_difficulty_signals():
    assert r.difficulty("word") == "low"
    assert r.difficulty("generate", item_kind="grammar") == "high"
    assert r.difficulty("answer", question="Why did the fox run home?") == "high"
    assert r.difficulty("answer", question=" ".join(["word"] * 13)) == "high"
    assert r.difficulty("generate", translation=" ".join(["w"] * 21)) == "high"
    assert r.difficulty("generate") == "normal"
    assert r.difficulty("generate", retry=True) == "high" and r.difficulty("word", retry=True) == "normal"


def test_decide_starts_on_fast_per_the_owners_decision():
    steps = r.route("decide", "normal", {"fast", "standard", "deep"})
    assert [(s.tier, s.degraded) for s in steps] == [("fast", False), ("standard", False), ("deep", False)]


def test_weaker_tiers_after_the_cell_are_degraded_and_unconfigured_ones_skipped():
    steps = r.route("generate", "normal", {"fast", "standard", "deep"})
    assert [(s.tier, s.degraded) for s in steps] == [("standard", False), ("deep", False), ("fast", True)]
    assert [s.tier for s in r.route("generate", "normal", {"fast"})] == ["fast"]
    assert r.route("judge", "low", set()) == []


def test_brain_routes_overrides_single_cells_and_ignores_nonsense():
    t = r.routes('{"generate": {"normal": ["fast"]}, "decide": {"low": ["nope"]}, "word": 3}')
    assert t["generate"]["normal"] == ("fast",) and t["decide"]["low"] == r.ROUTES["decide"]["low"]
    assert r.routes("not json") == r.ROUTES


def test_moments_leave_the_output_reserve():
    assert r.moment_s("next_activity", "pc") == 5.0 and r.moment_s("next_activity", "camera") == 5.5
    assert r.moment_s("feedback", "pc") == 2.0


def test_estimated_cost_from_the_price_table():
    assert r.estimated_cost("claude-sonnet-5-5", 1_000_000, 0) == 2.0
    assert r.estimated_cost("unknown-model", 10, 10) is None
