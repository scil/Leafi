import pytest

from agent.vision.vlm import parse_verdict


def test_parse_verdict():
    v = parse_verdict('{"verified": true, "confidence": 0.85, "note": "在刷"}')
    assert v.verified and v.confidence == 0.85 and v.note == "在刷"


def test_parse_verdict_minimal():
    v = parse_verdict('{"verified": false, "confidence": 0}')
    assert not v.verified and v.note == ""


def test_parse_verdict_bad_json():
    with pytest.raises(ValueError):
        parse_verdict("not json")
