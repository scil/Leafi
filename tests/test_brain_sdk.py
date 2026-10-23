"""TD-1 (ADR-0017 §10): `anthropic` >= 1 on httpx2, one retry owner. Probes P-B1 and P-B6 of
`docs/research/2026-10-22-harness-libraries.md` §2. Nothing leaves the machine: a MockTransport answers."""

from __future__ import annotations

import anthropic
import httpx
import httpx2

from leafi.services.brain import BrainRequest, Intent
from leafi.services.brain.claude import ClaudeBrain


def _brain(settings, handler) -> ClaudeBrain:
    settings.anthropic_api_key = "test-key-not-real"
    brain = ClaudeBrain(settings)
    built = brain._get_client()  # the production construction, then only its transport swapped
    brain._client = built.with_options(
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)))
    return brain


def _request() -> BrainRequest:
    return BrainRequest(intent=Intent.EXPLAIN_WORD, window="The fox ran home.", target="fox")


def test_httpx_resolves_to_httpx2_and_the_sdk_is_1x():
    assert httpx is httpx2
    assert anthropic.__version__.split(".")[0] == "1"


def test_the_production_client_never_retries_or_traces(settings):
    settings.anthropic_api_key = "test-key-not-real"
    client = ClaudeBrain(settings)._get_client()
    assert client.max_retries == 0
    assert client.timeout == float(settings.brain_deadline_s)


async def test_p_b1_p_b6_exactly_leafis_attempts_reach_a_503_server(settings):
    """P-B1: with `max_retries=0` exactly N requests reach a 503 server - here N = 2, the backend's one retry
    (until M7's brain_call), with no SDK retries stacked on it. P-B6: the same on the upgraded SDK."""
    hits: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        hits.append(request)
        return httpx2.Response(503, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}})

    assert await _brain(settings, handler).run(_request()) is None
    assert len(hits) == 2
    assert all(r.url.host == "api.anthropic.com" for r in hits)
