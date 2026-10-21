"""The settings manifest agrees with the code that reads `.env`, and `.env.example` is generated from it (rev 8)."""

import copy
import json

import pytest

from leafi import envedit
from leafi.core import envschema
from leafi.core.envfile import EnvFile
from tests.test_architecture import ROOT

RAW = json.loads((ROOT / "config" / "env-schema.json").read_text(encoding="utf-8"))


def agree(data) -> list[str]:
    return envedit.agreement(envschema.parse(data), ROOT)


def test_manifest_loads_and_agrees_with_every_reader():
    m, mismatches = envedit.load()
    assert m is not None and mismatches == []


def test_env_example_is_generated_from_the_manifest():
    m, _ = envedit.load()
    assert (ROOT / ".env.example").read_bytes() == envedit.env_example(m), "run: python -m leafi env-example"


def test_generated_example_is_canonical_and_its_active_values_validate():
    m, _ = envedit.load()
    f = EnvFile.parse(envedit.env_example(m))
    assert f.problems() == []
    errors, _ = envedit.validate_whole(f.values())
    assert errors == {}


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d["keys"]["ASR_THREADS"]["default"]["leafi"].update(value="8"), "ASR_THREADS: default"),
    (lambda d: d["keys"]["ASR_THREADS"].update(type="float"), "ASR_THREADS: type"),
    (lambda d: d["keys"].pop("VAD_THRESHOLD"), "VAD_THRESHOLD: read by leafi"),
    (lambda d: d["keys"]["GATUS_TOKEN"]["default"]["compose:gatus"].update(empty="empty"), "GATUS_TOKEN: compose:gatus"),
    (lambda d: d["keys"]["OCR_VERSION"]["options"].append("PP-OCRv7"), "OCR_VERSION: options"),
    (lambda d: d["keys"]["SUPERVISE"]["options"].append("teapot"), "SUPERVISE: options"),
    (lambda d: d["keys"]["PC_INPUT_DEVICE"]["default"]["devices.yml:pc.input_device"].update(value="X"),
     "PC_INPUT_DEVICE: devices.yml:pc.input_device"),
    (lambda d: d["keys"]["WEEKLY_REPORT"]["validator"].update(fn="agent.parsers:nope"), "WEEKLY_REPORT: validator"),
    (lambda d: (d["keys"]["BARK_URL"].pop("secret", None), d["keys"]["BARK_URL"].update(type="text")),
     "BARK_URL: must be secret"),
    (lambda d: d["keys"]["REDACT_TERMS"].pop("privacy"), "REDACT_TERMS: must be a privacy key"),
    (lambda d: d["keys"]["ASR_HOTWORDS"].pop("gate"), "ASR_HOTWORDS=lexicon: must be gated"),
    (lambda d: d["keys"]["NOTIFY_WITH_SNAPSHOT"].update(example={"value": "true"}), "NOTIFY_WITH_SNAPSHOT: privacy key"),
    (lambda d: d["keys"]["ASR_BACKEND"].update(example={"value": "Sherpa"}), "ASR_BACKEND: active example"),
    (lambda d: (d["keys"]["GATUS_TOKEN"]["readers"].remove("compose:gatus"),
                d["keys"]["GATUS_TOKEN"]["default"].pop("compose:gatus")),
     "GATUS_TOKEN: used in config.yaml but compose:gatus"),
])
def test_agreement_catches_drift(mutate, expect):
    data = copy.deepcopy(RAW)
    mutate(data)
    found = agree(data)
    assert any(f.startswith(expect) for f in found), found


@pytest.mark.parametrize("mutate", [
    lambda d: d["keys"]["ASR_THREADS"].update(type="number"),
    lambda d: d["keys"]["SUPERVISE"].pop("options"),
    lambda d: d["keys"]["ASR_THREADS"].update(group="nowhere"),
    lambda d: d["keys"]["OCR_SNAP"]["gate"].update(values=["sometimes"]),
    lambda d: d["keys"]["ASR_THREADS"].update(help="costs $5"),
    lambda d: d["groups"][0].pop("title"),
    lambda d: d.update(keys=["not", "a", "mapping"]),
    lambda d: d["keys"]["ASR_THREADS"].update(default={"leafi": "4"}),
])
def test_bad_shape_is_a_schema_error(mutate):
    data = copy.deepcopy(RAW)
    mutate(data)
    with pytest.raises(envschema.SchemaError):
        envschema.parse(data)


def _root_with(tmp_path, data):
    """A repository root with every file agreement reads, and a modified manifest."""
    import shutil

    for rel in ("docker-compose.yml", "config/devices.yml", "config/gatus/config.yaml", "scripts/win/timing.ps1",
                *[p.relative_to(ROOT).as_posix() for p in (ROOT / "config" / "frigate").glob("*.yml")]):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    (tmp_path / "config" / "env-schema.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_a_weakened_manifest_still_masks_floor_secrets_and_shows_no_values(tmp_path):
    data = copy.deepcopy(RAW)
    data["keys"]["BARK_URL"].pop("secret", None)
    data["keys"]["BARK_URL"]["type"] = "text"
    root = _root_with(tmp_path / "repo", data)
    env = tmp_path / ".env"
    env.write_bytes(b"BARK_URL=https://api.day.app/canary-bark\nASR_THREADS=4\n")
    body = envedit.view(env, root=root)
    assert body["agreement"]
    assert "canary-bark" not in repr(body)
    assert all("value" not in k for g in body["groups"] for k in g["keys"])


def test_gated_bool_values_are_not_offered():
    keys = {k["key"]: k for g in envedit.view(ROOT / "no-such.env")["groups"] for k in g["keys"]}
    assert keys["PRON_AUTO_JUDGE"]["options"] == ["false"]
    assert keys["AUDIO_KEEP_CLIPS"]["options"] == ["true", "false"]


def test_a_broken_manifest_makes_the_page_read_only(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "env-schema.json").write_text("{not json", encoding="utf-8")
    (tmp_path / ".env").write_bytes(b"ASR_THREADS=4\n")
    body = envedit.view(tmp_path / ".env", root=tmp_path)
    assert "manifest_error" in body and body["groups"] == []
    r = envedit.save({"digest": "x", "ops": {}}, path=tmp_path / ".env", data_dir=tmp_path / "data", root=tmp_path)
    assert r.body["ok"] is False
