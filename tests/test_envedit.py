"""The `.env` catalog and save coordinator (design §3-§5): gates, privacy confirmations, secrets, file-only validation."""

import argparse
import re

import pytest
from dotenv import dotenv_values

from leafi import envedit
from leafi.core.config import Settings as LeafiSettings
from leafi.core.envfile import EnvFile, read_state
from tests.test_architecture import ROOT


def save(tmp_path, ops, confirm=None, **kw):
    env = tmp_path / ".env"
    return envedit.save({"digest": read_state(env)[1], "ops": ops, "confirm": confirm or {}},
                        path=env, data_dir=tmp_path / "data", **kw)


@pytest.fixture
def env(tmp_path):
    p = tmp_path / ".env"
    p.write_bytes(b"# ===== S =====\nASR_THREADS=4\nTELEGRAM_BOT_TOKEN=canary-secret-123\nTARGET_BRUSH_SECONDS=90\n")
    return p


# ---------------------------------------------------------------- catalog


def test_every_known_key_is_catalogued_and_has_an_activation():
    cat = envedit.catalog()
    from agent.config import Settings as HabitSettings

    keys = {n.upper() for n in LeafiSettings.model_fields} | {n.upper() for n in HabitSettings.model_fields}
    keys |= set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    keys |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", (ROOT / "docker-compose.yml").read_text(encoding="utf-8")))
    assert keys <= set(cat.entries)
    readers = {r for e in cat.entries.values() for r in e.readers}
    assert all(envedit.activation(r) for r in readers), [r for r in readers if not envedit.activation(r)]


def test_gated_values_are_never_offered():
    cat = envedit.catalog()
    for key in ("ASR_BACKEND", "OCR_BACKEND", "BRAIN_BACKEND", "ASR_HOTWORDS", "OCR_SNAP"):
        options = envedit.allowed(cat.entries[key])
        assert options and not any(envedit.gated(cat.entries[key], o) for o in options), key
    assert "ollama" not in envedit.allowed(cat.entries["BRAIN_BACKEND"])
    assert "auto" not in envedit.allowed(cat.entries["OCR_SNAP"])


def test_every_credential_like_name_is_in_the_secret_table():
    from agent.config import Settings as HabitSettings

    names = {n.upper() for n in LeafiSettings.model_fields} | {n.upper() for n in HabitSettings.model_fields}
    names |= set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    assert {n for n in names if envedit.SECRET_NAME.search(n)} <= envedit.SECRET_KEYS


def test_per_reader_defaults_surface_the_traps():
    cat = envedit.catalog()
    assert cat.entries["GO2RTC_URL"].defaults["leafi"] != cat.entries["GO2RTC_URL"].defaults["habit agent"]
    assert cat.entries["GATUS_TOKEN"].defaults["compose:gatus"].startswith("change-me")
    assert "logon task" in cat.entries["TASK_REPEAT_MIN"].readers
    assert "VAR" not in cat.entries  # a ${VAR} inside a comment reads nothing


def test_view_masks_secrets_and_unknown_keys(env):
    body = envedit.view(env)
    assert "canary-secret-123" not in repr(body)
    keys = {k["key"]: k for g in body["groups"] for k in g["keys"]}
    assert keys["TELEGRAM_BOT_TOKEN"]["state"] == "set" and "value" not in keys["TELEGRAM_BOT_TOKEN"]
    stale = keys["TARGET_BRUSH_SECONDS"]
    assert stale["secret"] and not stale["editable"] and "value" not in stale
    assert keys["ASR_THREADS"]["value"] == "4"


def test_view_of_a_non_canonical_file_shows_no_values(tmp_path):
    p = tmp_path / ".env"
    p.write_bytes(b'ASR_THREADS=4\nCAM_PASSWORD="x y"\n')
    body = envedit.view(p)
    assert body["problems"] and body["problems"][0]["line"] == 2
    assert all("value" not in k and not k["editable"] for g in body["groups"] for k in g["keys"])


# ---------------------------------------------------------------- save


def test_save_is_all_or_nothing_and_names_the_rule_not_the_value(env, tmp_path):
    before = env.read_bytes()
    r = save(tmp_path, {"ASR_THREADS": {"op": "set", "value": "eight-xyz"}, "VAD_THRESHOLD": {"op": "set", "value": "0.4"}})
    assert r.body["ok"] is False and "ASR_THREADS" in r.body["errors"]
    assert "eight-xyz" not in repr(r.body)
    assert env.read_bytes() == before


@pytest.mark.parametrize("value", ["yes", "1", "on", "true"])
def test_gates_hold_on_typed_values(env, tmp_path, value):
    r = save(tmp_path, {"PRON_AUTO_JUDGE": {"op": "set", "value": value}})
    assert r.body["errors"]["PRON_AUTO_JUDGE"].startswith("gated")


@pytest.mark.parametrize("value", ["whisper", "Sherpa"])
def test_backends_are_checked_server_side(env, tmp_path, value):
    r = save(tmp_path, {"ASR_BACKEND": {"op": "set", "value": value}})
    assert "ASR_BACKEND" in r.body["errors"]


def test_privacy_keys_need_a_confirmation_bound_to_the_value(env, tmp_path):
    ops = {"NOTIFY_WITH_SNAPSHOT": {"op": "set", "value": "true"}}
    assert "NOTIFY_WITH_SNAPSHOT" in save(tmp_path, ops).body["errors"]
    wrong = {"NOTIFY_WITH_SNAPSHOT": envedit.confirmation("false")}
    assert "NOTIFY_WITH_SNAPSHOT" in save(tmp_path, ops, wrong).body["errors"]
    right = {"NOTIFY_WITH_SNAPSHOT": envedit.confirmation("true")}
    r = save(tmp_path, ops, right)
    assert r.body["ok"] is True
    assert dotenv_values(env)["NOTIFY_WITH_SNAPSHOT"] == "true"
    assert "restart the habit agent" in r.body["activation"]


def test_unknown_keys_accept_only_removal(env, tmp_path):
    assert "TARGET_BRUSH_SECONDS" in save(tmp_path, {"TARGET_BRUSH_SECONDS": {"op": "set", "value": "1"}}).body["errors"]
    r = save(tmp_path, {"TARGET_BRUSH_SECONDS": {"op": "unset"}})
    assert r.body["ok"] is True
    assert "TARGET_BRUSH_SECONDS" not in dotenv_values(env)


def test_whole_file_validation_ignores_the_process_environment(env, tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_THREADS", "not-a-number")
    r = save(tmp_path, {"ASR_THREADS": {"op": "set", "value": "6"}})
    assert r.body["ok"] is True
    assert any("ASR_THREADS" in w and "environment" in w for w in r.body["warnings"])


def test_stale_digest_is_a_conflict(env, tmp_path):
    r = envedit.save({"digest": "0" * 64, "ops": {"ASR_THREADS": {"op": "set", "value": "6"}}},
                     path=env, data_dir=tmp_path / "data")
    assert r.status == 409


@pytest.mark.parametrize("body", [
    {"digest": "x", "ops": {"A": {"op": "set"}}},
    {"digest": "x", "ops": {"A": {"op": "empty", "value": ""}}},
    {"digest": "x", "ops": {"A": {"op": "drop"}}},
    {"digest": "x", "ops": {"a b": {"op": "unset"}}},
    {"digest": "x", "ops": {}, "extra": 1},
])
def test_malformed_bodies_are_400(tmp_path, body):
    assert envedit.save(body, path=tmp_path / ".env", data_dir=tmp_path / "data").status == 400


def test_cmd_setup_keeps_line_endings_and_position(tmp_path, monkeypatch):
    from leafi import cli

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_bytes(b"A_KEY_X=1\r\nREDACT_TERMS=old\r\nZ=2\r\n")
    assert cli.cmd_setup(argparse.Namespace(redact="Ann,Some School")) == 0
    assert (tmp_path / ".env").read_bytes() == b"A_KEY_X=1\r\nREDACT_TERMS='Ann,Some School'\r\nZ=2\r\n"
    assert EnvFile.parse((tmp_path / ".env").read_bytes()).values()["REDACT_TERMS"] == "Ann,Some School"


def test_cmd_setup_creates_a_missing_env(tmp_path, monkeypatch):
    from leafi import cli

    monkeypatch.chdir(tmp_path)
    assert cli.cmd_setup(argparse.Namespace(redact="Ann")) == 0
    assert dotenv_values(tmp_path / ".env")["REDACT_TERMS"] == "Ann"
