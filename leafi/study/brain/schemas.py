"""Output schemas of the Brain's purposes (ADR-0017 §5; M7 design D6).

Every output is a Pydantic v2 model. `api_schema(Model)` turns its JSON schema into what Anthropic's structured
outputs accept: the keywords they support are kept, the constraints they do not (lengths, bounds, item counts) are
dropped — the model keeps them, so Pydantic still enforces them after parsing — every object is closed, and any
other construct raises, so an unsupported schema fails a unit test rather than a session. Unions are plain
`A | B` unions of models with a `kind` literal (a discriminated union would emit `oneOf` + `discriminator`).

The `decide` output parses in two levels (D6, T13): the envelope (the activity's kind and selection fields, the
alternative, the echoed turn) strictly — a failure is `invalid` and the walk escalates; then `say_before`, each
rationale slot and each record separately, each dropped alone when invalid (ADR-0017 §7.1). In M7 `decide` carries
selection fields only: every content field comes from one `generate` call at construction (ADR-0017 §3.3 lets the
decision carry content; it is optional, and leaving it out keeps the schema far inside the vendor's limits).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

KEEP = {"type", "properties", "required", "items", "enum", "const", "anyOf", "allOf", "$ref", "$defs",
        "description", "additionalProperties"}
DROP = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
        "minItems", "maxItems", "default", "title", "pattern", "format"}


class SchemaUnsupported(ValueError):
    """The generated schema holds a construct structured outputs do not accept."""


def _walk(node: Any, path: str) -> Any:
    if isinstance(node, list):
        return [_walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in DROP:
            continue
        if k not in KEEP:
            raise SchemaUnsupported(f"{path}: {k!r} is not supported by structured outputs")
        if k in ("properties", "$defs"):
            out[k] = {name: _walk(sub, f"{path}.{k}.{name}") for name, sub in v.items()}
        else:
            out[k] = _walk(v, f"{path}.{k}")
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


def api_schema(model: type[BaseModel]) -> dict:
    """The schema to send for `model`: byte-stable for a given model (sorted keys when serialised)."""
    return _walk(model.model_json_schema(), model.__name__)


def schema_bytes(model: type[BaseModel]) -> bytes:
    return json.dumps(api_schema(model), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def limits(schema: dict) -> tuple[int, int]:
    """(optional parameters, union-typed parameters) of a schema, to check against the vendor's limits."""
    optional = unions = 0

    def walk(node: Any) -> None:
        nonlocal optional, unions
        if isinstance(node, list):
            for v in node:
                walk(v)
            return
        if not isinstance(node, dict):
            return
        if "properties" in node:
            optional += len(set(node["properties"]) - set(node.get("required", ())))
        if "anyOf" in node:
            unions += 1
        for v in node.values():
            walk(v)

    walk(schema)
    return optional, unions


# ---------------------------------------------------------------- decide (ADR-0017 §5)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadListen(_Closed):
    kind: Literal["read_listen"]
    page: Literal["current", "next", "familiar"]
    from_sentence: int = Field(ge=0)  # 0 with to_sentence 0: the rest of the page
    to_sentence: int = Field(ge=0)


class ReadAloud(_Closed):
    kind: Literal["read_aloud"]
    page: Literal["current", "next", "familiar"]
    from_sentence: int = Field(ge=0)
    to_sentence: int = Field(ge=0)


class PractiseErrors(_Closed):
    kind: Literal["practise_errors"]
    candidate_ids: list[str] = Field(max_length=20)  # rendered ids, e.g. "m12" (D15)


class ReviewAnki(_Closed):
    kind: Literal["review_anki"]
    max_cards: int = Field(ge=1, le=20)


class RecallItems(_Closed):
    kind: Literal["recall_items"]
    item_ids: list[str] = Field(max_length=20)  # "i7"


class TeachItems(_Closed):
    kind: Literal["teach_items"]
    item_ids: list[str] = Field(max_length=10)


class AddCards(_Closed):
    kind: Literal["add_cards"]
    item_ids: list[str] = Field(max_length=10)


class Quiz(_Closed):
    kind: Literal["quiz"]
    evidence_sentence_ids: list[str] = Field(max_length=20)  # "s<page_read_id>.<index>"


class LearnerQuestions(_Closed):
    kind: Literal["learner_questions"]
    max_turns: int = Field(ge=1, le=5)


class Break(_Closed):
    kind: Literal["break"]
    seconds: int = Field(ge=1, le=120)


class End(_Closed):
    kind: Literal["end"]


ActivitySpec = (ReadListen | ReadAloud | PractiseErrors | ReviewAnki | RecallItems | TeachItems | AddCards | Quiz
                | LearnerQuestions | Break | End)


class Rationale(_Closed):
    evidence: str = Field(max_length=150)
    strategy: str = Field(max_length=150)
    intention: str = Field(max_length=150)


class Assessment(_Closed):
    kind: Literal["assessment"]
    activity_id: str  # a rendered activity id, "a<id>"
    text: str = Field(max_length=500)


class ItemIgnored(_Closed):
    kind: Literal["item_ignored"]  # the only status the Brain may request (§6.2: `* → ignored`)
    item_id: str


class BookNote(_Closed):
    kind: Literal["book_note"]
    topic: str = Field(max_length=100)
    characters: str = Field(max_length=200)
    summary: str = Field(max_length=200)


Record = Assessment | ItemIgnored | BookNote


class Decision(_Closed):
    """The one `decide` schema of a session (byte-stable across sessions, so the vendor's compiled schema is
    reused, O3)."""

    activity: ActivitySpec
    has_alternative: bool
    alternative: ActivitySpec  # ignored unless has_alternative (no nullable union: it would cost a union slot)
    say_before: str = Field(max_length=300)
    rationale: Rationale
    records: list[Record] = Field(max_length=5)
    turn: str


ACTIVITY = TypeAdapter(ActivitySpec)
RECORD = TypeAdapter(Record)


class ParsedDecision(BaseModel):
    activity: Any
    alternative: Any | None
    turn: str
    say_before: str | None
    rationale: Rationale | None
    records: list[Any]
    dropped: list[str]  # D4's rejection codes with their field paths, for the record


def parse_decision(raw: Any) -> ParsedDecision:
    """Two-level validation (D6). Raises `ValidationError` / `ValueError` when the envelope is invalid (the caller
    turns that into D4's codes); every other part is dropped alone and reported in `dropped`."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    activity = ACTIVITY.validate_python(raw.get("activity"))
    if not isinstance(raw.get("turn"), str):
        raise ValueError("turn missing")
    dropped: list[str] = []
    alternative = None
    if raw.get("has_alternative") is True:
        try:
            alternative = ACTIVITY.validate_python(raw.get("alternative"))
        except ValidationError:
            dropped.append("type at alternative")
    say = raw.get("say_before")
    if not isinstance(say, str) or len(say) > 300:
        dropped.append("too_long at say_before" if isinstance(say, str) else "type at say_before")
        say = None
    try:
        rationale = Rationale.model_validate(raw.get("rationale"))
    except ValidationError:
        rationale = None
        dropped.append("type at rationale")
    records = []
    for i, r in enumerate(raw.get("records") or [] if isinstance(raw.get("records"), list) else []):
        try:
            records.append(RECORD.validate_python(r))
        except ValidationError:
            dropped.append(f"type at records[{i}]")
    return ParsedDecision(activity=activity, alternative=alternative, turn=raw["turn"], say_before=say,
                          rationale=rationale, records=records, dropped=dropped)
