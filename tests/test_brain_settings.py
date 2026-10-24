"""The Brain's tier settings (M7 design D9): tier keys, the read-time legacy fallback, the fingerprint over the
effective values, and the gate on an Ollama entry."""

from __future__ import annotations

from leafi import envedit
from leafi.core.config import Settings, effective_tiers, tier_problems
from leafi.core.envschema import load as load_manifest
from leafi.privacy import versions


def test_defaults_and_tier_keys():
    assert effective_tiers({}) == {"fast": ("claude:claude-haiku-5-5",), "standard": ("claude:claude-sonnet-5-5",),
                                   "deep": ("claude:claude-opus-5-5",)}
    got = effective_tiers({"BRAIN_TIER_FAST": "claude:a, claude:b", "BRAIN_TIER_DEEP": ""})
    assert got["fast"] == ("claude:a", "claude:b") and got["deep"] == ()  # empty: not configured


def test_the_legacy_keys_decide_only_while_the_tier_key_is_unset():
    assert effective_tiers({"STUDY_BRAIN_MODEL": "claude-opus-4-8"})["deep"] == ("claude:claude-opus-4-8",)
    assert effective_tiers({"STUDY_BRAIN_MODEL": "claude-opus-4-8"})["standard"] == ("claude:claude-sonnet-5-5",)
    assert effective_tiers({"BRAIN_MODEL_CHEAP": "claude-haiku-4-5", "BRAIN_TIER_FAST": "claude:x"})["fast"] == \
        ("claude:x",)
    assert effective_tiers({"STUDY_BRAIN_MODEL": "gpt-5"})["deep"] == ()  # never routed
    assert any("not a Claude model" in p for p in tier_problems({"STUDY_BRAIN_MODEL": "gpt-5"}))
    assert any("is used" in p for p in tier_problems({"BRAIN_MODEL_CHEAP": "claude-haiku-4-5"}))


def test_settings_apply_the_fallback_only_to_keys_actually_given():
    assert Settings(_env_file=None).brain_tiers()["deep"] == ("claude:claude-opus-5-5",)
    s = Settings(_env_file=None, study_brain_model="claude-opus-4-8")
    assert s.brain_tiers()["deep"] == ("claude:claude-opus-4-8",)
    s = Settings(_env_file=None, study_brain_model="claude-opus-4-8", brain_tier_deep="claude:claude-opus-5-5")
    assert s.brain_tiers()["deep"] == ("claude:claude-opus-5-5",)


def test_the_fingerprint_follows_the_effective_tiers_not_the_keys_that_spell_them():
    key = b"k" * 32
    legacy = versions.fingerprint(key, {"STUDY_BRAIN_MODEL": "claude-opus-4-8"})
    moved = versions.fingerprint(key, {"BRAIN_TIER_DEEP": "claude:claude-opus-4-8"})
    assert legacy == moved  # retiring the legacy key with an equal tier key changes nothing
    assert versions.fingerprint(key, {"BRAIN_TIER_DEEP": "claude:claude-opus-5-5"}) != moved
    assert versions.fingerprint(key, {"BRAIN_ROUTES": '{"decide": {}}'}) != versions.fingerprint(key, {})


def test_an_ollama_entry_in_any_tier_is_gated():
    m = load_manifest()
    for name in ("BRAIN_TIER_FAST", "BRAIN_TIER_STANDARD", "BRAIN_TIER_DEEP"):
        k = m.keys[name]
        assert k.privacy and envedit.gated(k, "claude:claude-haiku-5-5, ollama:qwen3:8b")
        assert not envedit.gated(k, "claude:claude-haiku-5-5")
