"""Brain output schemas (M7 design D6): what is sent is accepted by structured outputs, stays byte-stable, keeps
inside the vendor's limits, and Pydantic still enforces what the API schema had to drop."""

from __future__ import annotations

import json
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from leafi.study.brain import schemas as sch

GOOD = {"activity": {"kind": "practise_errors", "candidate_ids": ["m12", "m14"]}, "has_alternative": True,
        "alternative": {"kind": "read_listen", "page": "current", "from_sentence": 0, "to_sentence": 0},
        "say_before": "Let's practise two words.",
        "rationale": {"evidence": "two misreadings", "strategy": "practise now", "intention": "fluency"},
        "records": [{"kind": "assessment", "activity_id": "a3", "text": "Read steadily."}], "turn": "t7"}


def _keys(node, out=None):
    out = set() if out is None else out
    if isinstance(node, dict):
        out.update(node)
        for v in node.values():
            _keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _keys(v, out)
    return out


def test_the_decide_schema_uses_only_supported_keywords_and_closes_every_object():
    s = sch.api_schema(sch.Decision)
    assert _keys(s) - sch.KEEP - set(_names(s)) == set()
    for obj in _objects(s):
        assert obj.get("additionalProperties") is False


def _names(node):
    """Property and $defs names (they are data, not keywords)."""
    out = []
    if isinstance(node, dict):
        for k in ("properties", "$defs"):
            out += list(node.get(k, {}))
        for v in node.values():
            out += _names(v)
    elif isinstance(node, list):
        for v in node:
            out += _names(v)
    return out


def _objects(node):
    if isinstance(node, dict):
        if "properties" in node:
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_the_schema_is_byte_identical_and_inside_the_vendor_limits():
    assert sch.schema_bytes(sch.Decision) == sch.schema_bytes(sch.Decision)
    optional, unions = sch.limits(sch.api_schema(sch.Decision))
    assert optional <= 24 and unions <= 16, (optional, unions)
    assert b"maxLength" not in sch.schema_bytes(sch.Decision)  # dropped for the API ...


def test_pydantic_still_enforces_what_the_api_schema_dropped():
    long = {**GOOD, "say_before": "x" * 301, "records": [{"kind": "assessment", "activity_id": "a3",
                                                           "text": "y" * 501}]}
    p = sch.parse_decision(long)  # ... but a reply over the limit is caught here, part by part
    assert p.say_before is None and p.records == [] and p.activity.kind == "practise_errors"
    assert "too_long at say_before" in p.dropped and "type at records[0]" in p.dropped
    with pytest.raises(ValidationError):
        sch.parse_decision({**GOOD, "activity": {"kind": "review_anki", "max_cards": 21}})


def test_the_envelope_is_strict_and_the_rest_is_dropped_alone():
    p = sch.parse_decision(GOOD)
    assert p.alternative.kind == "read_listen" and p.rationale.strategy == "practise now" and p.dropped == []
    with pytest.raises(ValidationError):
        sch.parse_decision({**GOOD, "activity": {"kind": "dance"}})
    with pytest.raises(ValueError):
        sch.parse_decision({k: v for k, v in GOOD.items() if k != "turn"})
    no_alt = sch.parse_decision({**GOOD, "has_alternative": False, "alternative": {"kind": "nonsense"}})
    assert no_alt.alternative is None and no_alt.dropped == []
    bad_rationale = sch.parse_decision({**GOOD, "rationale": {"evidence": "x"}})
    assert bad_rationale.rationale is None and bad_rationale.activity.kind == "practise_errors"


def test_an_unsupported_construct_fails_here_not_in_a_session():
    class A(BaseModel):
        kind: Literal["a"]

    class B(BaseModel):
        kind: Literal["b"]

    class Tagged(BaseModel):
        x: Annotated[A | B, Field(discriminator="kind")]

    with pytest.raises(sch.SchemaUnsupported, match="oneOf|discriminator"):
        sch.api_schema(Tagged)


def test_the_schema_round_trips_as_json_unchanged():
    s = sch.api_schema(sch.Decision)
    assert json.loads(json.dumps(s, ensure_ascii=False)) == s
