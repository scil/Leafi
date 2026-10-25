"""The Claude backend on the M7 port (design D3, D5, D6) through egress, against a fake server on a loopback
gateway port: the rendered body, content-only redaction (ADR-0021 E1), the budget, and each outcome."""

from __future__ import annotations

import json

import pytest

from leafi.core.ports import CallAttempt, Leaf, ModelRequest, Section, Turn
from leafi.privacy import destinations as dests
from leafi.services.brain.claude import ClaudeBrain
from leafi.study.brain import schemas
from tests.test_egress import _MESSAGE, server, world  # noqa: F401  (fixtures)


@pytest.fixture
def claude(world):  # noqa: F811
    w = world
    w.egress.registry["anthropic"] = dests.Destination("anthropic", "http", frozenset({"127.0.0.1"}), w.server.port,
                                                       dests.BRAIN, "cloud", dests.ANTHROPIC_HEADERS)
    w.settings.anthropic_api_key = "test-key"
    return w, ClaudeBrain(w.settings, egress=w.egress, model="claude-haiku-5-5")


def _req(w, leaves, *, budget=None, turns=None):
    turns = turns or (Turn("user", (Section("page", (Leaf("The fox ran home.", book=True),)),
                                    Section("last_activity", tuple(leaves)))),)
    return ModelRequest("generate", "claude-haiku-5-5", "You help a child read.", turns,
                        schemas.api_schema(schemas.Rationale), 512, "low", "off", 3.0, w.rocco, None, budget,
                        CallAttempt())


async def test_the_request_is_rendered_prepared_and_parsed(claude):
    w, brain = claude
    w.server.replies.append((200, _MESSAGE(json.dumps({"evidence": "e", "strategy": "s", "intention": "i"})), {}))
    rec = await brain.call(_req(w, [Leaf("Rocco said fox")]))
    assert rec.outcome == "ok" and rec.value == {"evidence": "e", "strategy": "s", "intention": "i"}
    (sent,) = w.server.requests
    body = json.loads(sent["body"])
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}  # one breakpoint on the system text
    texts = [b["text"] for b in body["messages"][0]["content"]]
    assert texts[0] == "<page>" and "<last_activity>" in texts and b"Rocco" not in sent["body"]  # pseudonymised
    assert body["output_config"]["effort"] == "low" and body["thinking"] == {"type": "disabled"}  # Haiku, off
    assert rec.transmissions == 1 and rec.sent == body and rec.received is not None


async def test_the_learner_context_ends_with_its_own_cache_breakpoint_on_the_wire(claude):
    """Owner decision 2026-10-24: the session-level learner context is cached after the system text."""
    w, brain = claude
    w.server.replies.append((200, _MESSAGE(json.dumps({"evidence": "e", "strategy": "s", "intention": "i"})), {}))
    turns = (Turn("user", (Section("learner_context", (Leaf("difficulty 'fox' 1.0", book=True),),
                                   cache=True),
                           Section("page", (Leaf("The fox ran home.", book=True),)))),)
    assert (await brain.call(_req(w, [], turns=turns))).outcome == "ok"
    blocks = json.loads(w.server.requests[0]["body"])["messages"][0]["content"]
    marked = [b["text"] for b in blocks if "cache_control" in b]
    assert marked == ["</learner_context>"]  # with the system text's: two breakpoints in all


async def test_a_learners_words_leave_redacted(claude):
    """ADR-0021 E1: a learner's words leave redacted by content (E6 removed the substitute they once carried)."""
    w, brain = claude
    w.server.replies.append((200, _MESSAGE(json.dumps({"evidence": "", "strategy": "", "intention": ""})), {}))
    leaves = [Leaf("Rocco said hose"), Leaf("a note about him")]
    rec = await brain.call(_req(w, leaves))
    assert rec.outcome == "ok"
    body = w.server.requests[0]["body"]
    assert b"said hose" in body and b"a note about him" in body
    assert b"Rocco" not in body


async def test_an_assistant_turn_leaves_redacted(claude):
    w, brain = claude
    w.server.replies.append((200, _MESSAGE(json.dumps({"evidence": "", "strategy": "", "intention": ""})), {}))
    turns = (Turn("user", (Section("page", (Leaf("The fox.", book=True),)),)),
             Turn("assistant", (Section("plan", (Leaf("Rocco struggles with fox"),)),)),
             Turn("user", (Section("turn", (Leaf("next"),)),)))
    rec = await brain.call(_req(w, [], turns=turns))
    body = w.server.requests[0]["body"]
    assert rec.outcome == "ok" and b"struggles with fox" in body and b"Rocco" not in body


async def test_over_budget_truncated_and_failed_outcomes(claude):
    w, brain = claude

    class Empty:
        def can_cover(self, first):
            return False

        def charge(self, first):
            raise AssertionError("never charged")

    rec = await brain.call(_req(w, [], budget=Empty()))
    assert rec.outcome == "over_budget" and w.server.requests == []
    msg = _MESSAGE("{\"evidence\": ")
    msg["stop_reason"] = "max_tokens"
    w.server.replies.append((200, msg, {}))
    rec = await brain.call(_req(w, []))
    assert (rec.outcome, rec.detail) == ("invalid", "truncated at .")
    w.server.replies += [(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}, {})]
    rec = await brain.call(_req(w, []))
    assert rec.outcome == "failed"
