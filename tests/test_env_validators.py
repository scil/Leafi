"""Validators are the consumers' own parsers (design §8.7-§8.9): import-safe, and really used by the consumer."""

import asyncio
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


def spy(monkeypatch, target, attr, result):
    calls = []

    def fake(text):
        calls.append(text)
        return result

    monkeypatch.setattr(target, attr, fake)
    return calls


def test_habit_parsers_drive_the_settings_methods(monkeypatch):
    from agent import config, parsers

    calls = spy(monkeypatch, parsers, "parse_weekly_report", ("sentinel", 1, 2))
    s = config.Settings(_env_file=None, weekly_report="TEXT-W", schedule="TEXT-S")
    assert s.parsed_weekly_report() == ("sentinel", 1, 2) and calls == ["TEXT-W"]
    calls = spy(monkeypatch, parsers, "parse_schedule", [("sentinel", "00:00")])
    assert s.parsed_schedule() == [("sentinel", "00:00")] and calls == ["TEXT-S"]


def test_timing_parsers_drive_resolve(monkeypatch):
    from leafi.core.config import Settings
    from leafi.ops import timing

    g = spy(monkeypatch, timing, "parse_grace", {"camera": 95.0})
    b = spy(monkeypatch, timing, "parse_backoff", (6.0, 30.0, 120.0, 300.0))
    t, problems = timing.resolve(Settings(_env_file=None, supervisor_grace="TEXT-G", keep_backoff_s="TEXT-B"))
    assert g == ["TEXT-G"] and b == ["TEXT-B"]
    assert t.grace["camera"] == 95.0 and t.keep_backoff_s == (6.0, 30.0, 120.0, 300.0) and problems == []


def test_active_hours_parser_drives_the_check(monkeypatch):
    from leafi.core.config import Settings
    from leafi.ops import checks

    calls = spy(monkeypatch, checks, "parse_active_hours", (3, 4))
    seen = []
    monkeypatch.setattr(checks, "_reg", lambda *a: 7)
    monkeypatch.setattr(checks, "hours_cover", lambda *a: seen.append(a) or True)
    check = next(c for c in checks.build(Settings(_env_file=None, active_hours="TEXT-H")) if c.name == "active-hours")
    assert calls == []  # parsed when the check runs, not at build time
    assert asyncio.run(check.run()) is True
    assert calls == ["TEXT-H"] and seen == [(7, 7, 3, 4)]


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
