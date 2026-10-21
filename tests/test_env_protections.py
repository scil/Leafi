"""The protection floor, proven through the page's own code paths (design §8.6-§8.7).

The expectations come from `leafi.envprotect`, not from the manifest, so a manifest edit cannot remove one.
"""

import pytest

from leafi import envedit, envprotect
from leafi.core.envfile import read_state

CHANGED = {"NOTIFY_WITH_SNAPSHOT": "true", "BOOK_LOOKUP": "openlibrary", "AUDIO_KEEP_CLIPS": "true",
           "EVAL_TRANSCRIPTS": "true", "REDACT_TERMS": "Ann", "BRAIN_BACKEND": "mock", "STUDY_BRAIN_MODEL": "other",
           "TTS_BACKEND_EN": "edge", "TTS_BACKEND_ZH": "kokoro"}
GATED = [*envprotect.GATE_FLOOR, ("PRON_AUTO_JUDGE", "yes"), ("PRON_AUTO_JUDGE", "1"), ("PRON_AUTO_JUDGE", "on")]


def save(tmp_path, ops, confirm=None):
    env = tmp_path / ".env"
    return envedit.save({"digest": read_state(env)[1], "ops": ops, "confirm": confirm or {}},
                        path=env, data_dir=tmp_path / "data")


@pytest.mark.parametrize("key", sorted(envprotect.SECRET_FLOOR))
def test_secret_values_never_leave_the_server(tmp_path, key):
    (tmp_path / ".env").write_bytes(f"{key}=canary-{key.lower()}\n".encode())
    assert f"canary-{key.lower()}" not in repr(envedit.view(tmp_path / ".env"))


def test_every_privacy_key_has_a_test_value():
    assert set(CHANGED) == envprotect.PRIVACY_FLOOR


@pytest.mark.parametrize("key", sorted(envprotect.PRIVACY_FLOOR))
def test_privacy_changes_need_a_value_bound_confirmation(tmp_path, key):
    (tmp_path / ".env").write_bytes(b"ASR_THREADS=4\n")
    ops = {key: {"op": "set", "value": CHANGED[key]}}
    assert key in save(tmp_path, ops).body["errors"]
    assert save(tmp_path, ops, {key: envedit.confirmation(CHANGED[key])}).body["ok"] is True


@pytest.mark.parametrize("key,value", GATED)
def test_gated_values_are_refused(tmp_path, key, value):
    (tmp_path / ".env").write_bytes(b"ASR_THREADS=4\n")
    r = save(tmp_path, {key: {"op": "set", "value": "x" if value == "*" else value}})
    assert key in r.body.get("errors", {}), r.body
