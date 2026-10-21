"""Validators are the consumers' own parsers (design §8.7-§8.9): import-safe, and really used by the consumer."""

import asyncio
import importlib
import json
import os
import re
import subprocess
import sys

import pytest

from leafi import envedit
from tests.test_architecture import ROOT

MODULES = sorted({k.validator.fn.split(":")[0] for k in envedit.load()[0].keys.values() if k.validator})

PROBE = r"""
import sys
sys.path.insert(0, sys.argv[1])
seen = []
def hook(event, args):
    if event == "open" and str(args[0]).replace("\\", "/").endswith(".env"):
        seen.append("open .env")
sys.addaudithook(hook)
import pydantic_settings
pydantic_settings.BaseSettings.__init__ = lambda self, *a, **k: seen.append("Settings()")
import importlib
importlib.import_module(sys.argv[2])
print("SEEN", seen)
"""


@pytest.mark.parametrize("module", MODULES)
def test_validator_modules_import_without_reading_env_or_building_settings(tmp_path, module):
    (tmp_path / ".env").write_text('POISON="unterminated\n', encoding="utf-8")
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP") if k in os.environ}
    out = subprocess.run([sys.executable, "-I", "-c", PROBE, str(ROOT), module], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "SEEN []" in out.stdout, out.stdout


def _run_settings_method(method):
    def run(field, text, monkeypatch):
        from agent import config

        return getattr(config.Settings(_env_file=None, **{field: text}), method)()
    return run


def _run_timing(field, text, monkeypatch):
    from leafi.core.config import Settings
    from leafi.ops import timing

    return timing.resolve(Settings(_env_file=None, **{field: text}))


def _run_checks_build(field, text, monkeypatch):
    from leafi.core.config import Settings
    from leafi.ops import checks

    monkeypatch.setattr(checks, "_reg", lambda *a: 7)
    built = checks.build(Settings(_env_file=None, **{field: text}))
    return [asyncio.run(c.run()) for c in built if c.name == "active-hours"]


# How to drive each consumer the manifest names; a new consumer must be added here, so its binding is tested.
CONSUMERS = {
    "agent.config:Settings.parsed_weekly_report": _run_settings_method("parsed_weekly_report"),
    "agent.config:Settings.parsed_schedule": _run_settings_method("parsed_schedule"),
    "leafi.ops.timing:resolve": _run_timing,
    "leafi.ops.checks:build": _run_checks_build,
}
BOUND = [k for k in envedit.load()[0].keys.values() if k.validator]


@pytest.mark.parametrize("key", BOUND, ids=[k.name for k in BOUND])
def test_the_declared_consumer_calls_the_declared_validator(monkeypatch, key):
    """Spy on exactly the function the manifest names and run exactly the consumer it names: the spy must receive the
    setting's text. Pointing a key at another parser (or another consumer) fails here."""
    assert key.validator.consumer in CONSUMERS, f"add a runner for {key.validator.consumer}"
    module, _, attr = key.validator.fn.partition(":")
    target = importlib.import_module(module)
    real = getattr(target, attr)
    good = next(d.value for r, d in key.default.items() if r in ("leafi", "habit agent"))
    calls = []
    monkeypatch.setattr(target, attr, lambda text: calls.append(text) or real(good))
    CONSUMERS[key.validator.consumer](key.name.lower(), "TEXT-" + key.name, monkeypatch)
    assert calls == ["TEXT-" + key.name]


def test_parsed_results_drive_the_consumers(monkeypatch):
    """The value a validator returns is what the consumer uses (not recomputed elsewhere)."""
    from leafi.core.config import Settings
    from leafi.ops import checks, timing

    monkeypatch.setattr(timing, "parse_grace", lambda text: {"camera": 95.0})
    monkeypatch.setattr(timing, "parse_backoff", lambda text: (6.0, 30.0, 120.0, 300.0))
    t, problems = timing.resolve(Settings(_env_file=None))
    assert t.grace["camera"] == 95.0 and t.keep_backoff_s == (6.0, 30.0, 120.0, 300.0) and problems == []
    monkeypatch.setattr(checks, "parse_active_hours", lambda text: (3, 4))
    monkeypatch.setattr(checks, "_reg", lambda *a: 7)
    seen = []
    monkeypatch.setattr(checks, "hours_cover", lambda *a: seen.append(a) or True)
    check = next(c for c in checks.build(Settings(_env_file=None)) if c.name == "active-hours")
    assert asyncio.run(check.run()) is True and seen == [(7, 7, 3, 4)]


NEW_DOMAIN_CONSTANTS = ["HOTWORDS_MODES", "SNAP_MODES", "LOOKUPS", "GLOBAL_VERIFY_MODES", "SPEAKER_BACKENDS", "CHANNELS"]


@pytest.mark.parametrize("name", NEW_DOMAIN_CONSTANTS)
def test_new_domain_constants_change_no_runtime_branch(name):
    """They declare what the page offers; no service reads them, so no service behaves differently."""
    uses = []
    for f in [*ROOT.joinpath("leafi").rglob("*.py"), *ROOT.joinpath("agent").rglob("*.py")]:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(rf"\b{name}\b", line) and not re.match(rf"^{name}\s*=", line):
                uses.append(f"{f.relative_to(ROOT)}:{i}")
    assert uses == []


def test_manifest_domains_name_existing_constants():
    data = json.loads((ROOT / "config" / "env-schema.json").read_text(encoding="utf-8"))
    domains = {k["domain"] for k in data["keys"].values() if "domain" in k}
    assert {d.split(":")[1] for d in domains} >= set(NEW_DOMAIN_CONSTANTS)
