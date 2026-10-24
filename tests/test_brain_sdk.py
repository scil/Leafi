"""TD-1 (ADR-0017 §10): `anthropic` >= 1 on httpx2, one retry owner. Probes P-B1 and P-B6 of
`docs/research/2026-10-22-harness-libraries.md` §2. Nothing leaves the machine: a MockTransport answers."""

from __future__ import annotations

import anthropic
import httpx
import httpx2

from leafi.services.brain import BrainRequest, Intent
from leafi.services.brain.claude import ClaudeBrain


def _brain(settings, handler) -> tuple[ClaudeBrain, int]:
    """The production construction through egress (M5c); only egress's wire transport is a mock."""
    from leafi.core import learner_store
    from leafi.core.storage import Store
    from leafi.privacy import settings as privacy
    from tests.egress_helpers import mock_egress

    settings.anthropic_api_key = "test-key-not-real"
    e = mock_egress(settings, handler)
    with Store(settings.db_path) as store:
        lid = learner_store.create(store, "Learner")
        privacy.set_school(store, lid, None)
    return ClaudeBrain(settings, egress=e), lid


def _request(lid: int | None = None) -> BrainRequest:
    return BrainRequest(intent=Intent.EXPLAIN_WORD, window="The fox ran home.", target="fox", learner_id=lid)


def test_httpx_resolves_to_httpx2_and_the_sdk_is_1x():
    assert httpx is httpx2
    assert anthropic.__version__.split(".")[0] == "1"


def test_the_production_client_never_retries_or_traces(settings):
    settings.anthropic_api_key = "test-key-not-real"
    client = ClaudeBrain(settings)._get_client()
    assert client.max_retries == 0
    assert client.timeout == float(settings.brain_deadline_s)


async def test_p_b1_p_b6_exactly_leafis_attempts_reach_a_503_server(settings):
    """P-B1: with `max_retries=0` exactly N requests reach a 503 server - here N = 2, the mediator's one retry
    (ADR-0018 §2; the backend's own loop is gone), with no SDK retries stacked on it. P-B6: the same on the
    upgraded SDK."""
    hits: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        hits.append(request)
        return httpx2.Response(503, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}})

    brain, lid = _brain(settings, handler)
    assert await brain.run(_request(lid)) is None
    assert len(hits) == 2
    assert all(r.url.host == "api.anthropic.com" and "x-leafi-token" not in r.headers for r in hits)


async def test_a_request_without_a_learner_is_never_sent(settings):
    hits: list = []
    brain, _ = _brain(settings, lambda r: hits.append(r) or httpx2.Response(200))
    assert await brain.run(_request(None)) is None and hits == []
