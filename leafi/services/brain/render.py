"""From a `ModelRequest` to the bytes a backend sends (M7 design D3, D6): the per-leaf filter, then the Anthropic
Messages body in the one rendering order, with its cache breakpoints. Shared by every backend on the port."""

from __future__ import annotations

from collections.abc import Callable

from leafi.core.ports import ModelRequest, Section, Turn
from leafi.core.provenance import Leaf, Provenance


class AssistantTurnWithheld(Exception):
    """A leaf of an earlier assistant turn may no longer leave (e.g. `cloud.text` switched off mid-practice): the
    conversation cannot be sent with a hole in it, so the request is refused (owner decision B2, rev 6 #15)."""


def filter_turns(turns: tuple[Turn, ...], may_send: Callable[[Leaf], bool]) -> tuple[tuple[Turn, ...], int]:
    """D3: every leaf the egress gate would refuse is replaced by its substitute (as page text: an expected word
    and its category come from the page and the harness) or dropped; returns the turns and how many were held."""
    held = 0
    out = []
    for t in turns:
        sections = []
        for s in t.sections:
            leaves = []
            for leaf in s.leaves:
                if may_send(leaf):
                    leaves.append(leaf)
                    continue
                if t.role == "assistant":
                    raise AssistantTurnWithheld(s.name)
                held += 1
                if leaf.substitute is not None:
                    leaves.append(Leaf(leaf.substitute, Provenance("page")))
            sections.append(Section(s.name, tuple(leaves), s.cache))
        out.append(Turn(t.role, tuple(sections), t.provenance))
    return tuple(out), held


def _escape(text: str, tag: str) -> str:
    return text.replace(f"</{tag}>", f"</ {tag}>")


def messages_body(req: ModelRequest, turns: tuple[Turn, ...], text: Callable[[Leaf], object]) -> dict:
    """The Anthropic Messages body. `text(leaf)` makes egress's `Text` (or a plain string for a local test).

    Order (D6): the frozen system text with one `cache_control` breakpoint; then each turn's sections as tagged
    blocks in the order the caller gave them (stable first, volatile last). A section marked `cache` (the
    session-level learner context of `generate`, `answer`, `judge`) ends with a breakpoint; a multi-turn request
    may add one on the last block of its first assistant turn (C3)."""
    messages = []
    first_assistant = True
    for t in turns:
        blocks: list[dict] = []
        for s in t.sections:
            if not s.leaves:
                continue
            blocks.append({"type": "text", "text": f"<{s.name}>"})
            blocks.extend({"type": "text", "text": text(Leaf(_escape(leaf.value, s.name), leaf.prov))}
                          for leaf in s.leaves)
            close = {"type": "text", "text": f"</{s.name}>"}
            if s.cache and t.role == "user":  # the session's learner context: one more breakpoint (owner 2026-10-24)
                close["cache_control"] = {"type": "ephemeral"}
            blocks.append(close)
        if not blocks:
            blocks.append({"type": "text", "text": "(nothing)"})
        if t.role == "assistant" and first_assistant and len(turns) > 1:
            blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
            first_assistant = False
        messages.append({"role": t.role, "content": blocks})
    body: dict = {
        "model": req.model, "max_tokens": req.max_tokens,
        "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "output_config": {"format": {"type": "json_schema", "schema": req.schema}, "effort": req.effort},
    }
    thinking = thinking_param(req.model, req.thinking)
    if thinking is not None:
        body["thinking"] = thinking
    return body


def thinking_param(model: str, wanted: str) -> dict | None:
    """D6: thinking off where the model allows it (Haiku 5.5 `disabled`; Sonnet 5.5 `between_tools`, which for a
    call without tools is off); Opus 5.5 cannot turn it off, so it runs adaptive (omitted) at the effort given."""
    if wanted != "off":
        return None
    if "haiku" in model:
        return {"type": "disabled"}
    if "sonnet-5-5" in model:
        return {"type": "between_tools"}
    return None
