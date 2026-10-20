import pytest

from agent.vision.vlm import parse_verdict, verdict


def test_parse_verdict():
    v = parse_verdict('{"verified": true, "confidence": 0.85, "note": "在刷"}')
    assert v.verified and v.confidence == 0.85 and v.note == "在刷"


def test_parse_verdict_minimal():
    v = parse_verdict('{"verified": false, "confidence": 0}')
    assert not v.verified and v.note == ""


def test_parse_verdict_bad_json():
    with pytest.raises(ValueError):
        parse_verdict("not json")


@pytest.mark.asyncio
async def test_no_prompt_and_unknown_kind_is_unavailable_not_crash():
    """kind 不在内置 PROMPTS 里又没自带提问:当成终裁不可用,别把会话炸掉。"""
    assert await verdict(["ZmFrZQ=="], kind="feed_the_cat", prompt="") is None
