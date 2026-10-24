"""Egress for tests that check what a caller sends: `httpx2.MockTransport(handler)` answers, nothing resolves or
connects, and the attempt rows are real (M5 design D5–D9)."""

from __future__ import annotations

import httpx2

from leafi.privacy import egress, runtime, secret


async def test_net(host, port, ttl):
    return ["192.0.2.1"]  # TEST-NET-1: never looked up, never reached (the mock transport answers)


def mock_egress(settings, handler, *, install: bool = True) -> egress.Egress:
    secret._forget_cache()
    e = egress.Egress(settings, env_file=None, inner=httpx2.MockTransport(handler), resolve=test_net)
    if install:
        runtime.use(e)
    return e
