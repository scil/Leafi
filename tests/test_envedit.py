"""The `.env` save coordinator (design §5, rev 8): typed gates, privacy confirmations, masking, lists, all-or-nothing."""


import pytest
from dotenv import dotenv_values

from leafi import envedit
from leafi.core.envfile import EnvFile, read_state


def save(tmp_path, ops, confirm=None, **kw):
    env = tmp_path / ".env"
    return envedit.save({"digest": read_state(env)[1], "ops": ops, "confirm": confirm or {}},
                        path=env, data_dir=tmp_path / "data", **kw)


@pytest.fixture
def env(tmp_path):
    p = tmp_path / ".env"
    p.write_bytes(b"# ===== S =====\nASR_THREADS=4\nTELEGRAM_BOT_TOKEN=canary-secret-123\nTARGET_BRUSH_SECONDS=90\n")
    return p


def keys_of(body):
    return {k["key"]: k for g in body["groups"] for k in g["keys"]}


def test_view_masks_secrets_and_unknown_keys(env):
    body = envedit.view(env)
    assert "canary-secret-123" not in repr(body)
    keys = keys_of(body)
    assert keys["TELEGRAM_BOT_TOKEN"]["state"] == "set" and "value" not in keys["TELEGRAM_BOT_TOKEN"]
    stale = keys["TARGET_BRUSH_SECONDS"]
    assert stale["secret"] and not stale["editable"] and "value" not in stale
    assert keys["ASR_THREADS"]["value"] == "4"
    assert keys["SUPERVISE"]["type"] == "list" and "habit-agent" in keys["SUPERVISE"]["options"]
    assert "ollama" not in keys["BRAIN_BACKEND"]["options"]  # gated values are never offered


def test_view_of_a_non_canonical_file_shows_no_values(tmp_path):
    p = tmp_path / ".env"
    p.write_bytes(b'ASR_THREADS=4\nCAM_PASSWORD="x $y"\n')
    body = envedit.view(p)
    assert body["problems"] and body["problems"][0]["line"] == 2
    assert all("value" not in k and not k["editable"] for g in body["groups"] for k in g["keys"])


def test_save_is_all_or_nothing_and_names_the_rule_not_the_value(env, tmp_path):
    before = env.read_bytes()
    r = save(tmp_path, {"ASR_THREADS": {"op": "set", "value": "eight-xyz"}, "VAD_THRESHOLD": {"op": "set", "value": "0.4"}})
    assert r.body["ok"] is False and "ASR_THREADS" in r.body["errors"]
    assert "eight-xyz" not in repr(r.body)
    assert env.read_bytes() == before


@pytest.mark.parametrize("value", ["whisper", "Sherpa"])
def test_backends_are_checked_server_side(env, tmp_path, value):
    r = save(tmp_path, {"ASR_BACKEND": {"op": "set", "value": value}})
    assert "ASR_BACKEND" in r.body["errors"]


def test_lists_are_written_in_option_order_and_reject_unknown_or_repeated_items(env, tmp_path):
    assert save(tmp_path, {"SUPERVISE": {"op": "set", "value": "gatus, docker"}}).body["ok"] is True
    assert dotenv_values(env)["SUPERVISE"] == "docker,gatus"
    for bad in ("docker,docker", "docker,teapot"):
        assert "SUPERVISE" in save(tmp_path, {"SUPERVISE": {"op": "set", "value": bad}}).body["errors"]
    assert save(tmp_path, {"REQUIRED_CHANNELS": {"op": "empty"}}).body["ok"] is True
    assert dotenv_values(env)["REQUIRED_CHANNELS"] == ""


@pytest.mark.parametrize("value", ["off", "1", "yes", "T"])
def test_bool_values_are_only_the_offered_spellings(env, tmp_path, value):
    assert "AUDIO_KEEP_CLIPS" in save(tmp_path, {"AUDIO_KEEP_CLIPS": {"op": "set", "value": value}}).body["errors"]


def test_ocr_rotations_keep_their_order_and_refuse_bad_values(env, tmp_path):
    """OCR design 2026-10-25 O1: a `text` key with a validator, because the `list` type would re-sort the angles."""
    assert save(tmp_path, {"OCR_ROTATIONS": {"op": "set", "value": "270,90,0"}}).body["ok"] is True
    assert dotenv_values(env)["OCR_ROTATIONS"] == "270,90,0"
    for bad in ("45", "90,90", " , "):
        assert "OCR_ROTATIONS" in save(tmp_path, {"OCR_ROTATIONS": {"op": "set", "value": bad}}).body["errors"]
    assert "OCR_ROTATIONS" in save(tmp_path, {"OCR_ROTATIONS": {"op": "empty"}}).body["errors"]


def test_the_cli_removing_a_retired_key_reports_an_unreadable_env(tmp_path, monkeypatch, capsys):
    from leafi import cli

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").mkdir()
    assert cli._unset_env("REDACT_TERMS") == 1
    assert "cannot be read" in capsys.readouterr().out


def test_empty_is_refused_where_a_reader_would_reject_it(env, tmp_path):
    assert "ASR_THREADS" in save(tmp_path, {"ASR_THREADS": {"op": "empty"}}).body["errors"]


def test_validator_errors_block_and_warnings_save(env, tmp_path):
    r = save(tmp_path, {"WEEKLY_REPORT": {"op": "set", "value": "sunday-evening"}})
    assert r.body["errors"]["WEEKLY_REPORT"].startswith("not accepted by agent.parsers")
    assert "sunday-evening" not in repr(r.body)
    r = save(tmp_path, {"KEEP_BACKOFF_S": {"op": "set", "value": "5,soon"}})
    assert r.body["ok"] is True and any("KEEP_BACKOFF_S" in w for w in r.body["warnings"])


@pytest.mark.parametrize("key,value", [("KEEP_CRASH_EXITS", "1" + "0" * 400), ("KEEP_CRASH_WINDOW_MIN", "inf"),
                                       ("TASK_REPEAT_MIN", "2147483648"), ("SUPERVISOR_POLL_S", "nan")])
def test_absurd_timing_values_are_reported_not_crashing(env, tmp_path, key, value):
    r = save(tmp_path, {key: {"op": "set", "value": value}})
    assert r.status == 200
    # the timing fallback reports it as a warning; the catch-all ("could not validate") would not count
    assert r.body.get("ok") is True and any("range" in w for w in r.body["warnings"]), r.body


def test_absurd_timing_values_fall_back_for_the_supervisor():
    from leafi.core.config import Settings
    from leafi.ops import timing

    t, problems = timing.resolve(Settings(_env_file=None, keep_crash_exits=10**400, keep_crash_window_min=float("inf"),
                                          task_repeat_min=2**31))
    assert "range" in problems
    assert (t.keep_crash_exits, t.keep_crash_window_min, t.task_repeat_min) == (3, 30.0, 5)
    assert "inf" not in "\n".join(timing.as_env(t))
    t, problems = timing.resolve(Settings(_env_file=None, keep_backoff_s="5,30,120,3000000",
                                          keep_crash_window_min=100001))
    assert "range" in problems and t.keep_backoff_s == (5.0, 30.0, 120.0, 300.0)


def test_an_unreadable_env_keeps_the_page_answering(tmp_path):
    (tmp_path / ".env").mkdir()
    body = envedit.view(tmp_path / ".env")
    assert body["problems"] and body["groups"] == []


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


def test_the_cli_removes_a_retired_key_keeping_line_endings_and_the_other_lines(tmp_path, monkeypatch):
    from leafi import cli

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_bytes(b"A_KEY_X=1\r\nREDACT_TERMS=old\r\nZ=2\r\n")
    assert cli._unset_env("REDACT_TERMS") == 0  # the shared writer comments a removed line out, in place
    assert (tmp_path / ".env").read_bytes() == b"A_KEY_X=1\r\n# REDACT_TERMS=old\r\nZ=2\r\n"
    assert EnvFile.parse((tmp_path / ".env").read_bytes()).problems() == []
