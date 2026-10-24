"""The composition root's tiers (M7 design D9, D10): entries become backends; Ollama stays gated; locality by D1."""

from __future__ import annotations

from leafi.core.config import Settings
from leafi.services.brain import tiers as brain_tiers
from leafi.services.brain.claude import ClaudeBrain
from leafi.services.brain.mock import MockModel


def test_entries_become_backends_and_ollama_stays_gated(caplog):
    s = Settings(_env_file=None, brain_tier_fast="claude:claude-haiku-5-5, ollama:qwen3:8b",
                 brain_tier_standard="mock:m", brain_tier_deep="", local_models="ollama:qwen3:8b")
    tiers, locality = brain_tiers.build(s)
    (fast,) = tiers["fast"]
    assert isinstance(fast[0], ClaudeBrain) and fast[0].model == "claude-haiku-5-5" == fast[1]
    assert isinstance(tiers["standard"][0][0], MockModel) and tiers["deep"] == []
    assert "gated until Ollama is measured" in caplog.text
    assert locality(fast[0], fast[1]) == "cloud" and locality(tiers["standard"][0][0], "m") == "local"
