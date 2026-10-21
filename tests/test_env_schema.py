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
])
def test_bad_shape_is_a_schema_error(mutate):
    data = copy.deepcopy(RAW)
    mutate(data)
    with pytest.raises(envschema.SchemaError):
        envschema.parse(data)


def test_a_broken_manifest_makes_the_page_read_only(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "env-schema.json").write_text("{not json", encoding="utf-8")
    (tmp_path / ".env").write_bytes(b"ASR_THREADS=4\n")
    body = envedit.view(tmp_path / ".env", root=tmp_path)
    assert "manifest_error" in body and body["groups"] == []
    r = envedit.save({"digest": "x", "ops": {}}, path=tmp_path / ".env", data_dir=tmp_path / "data", root=tmp_path)
    assert r.body["ok"] is False
