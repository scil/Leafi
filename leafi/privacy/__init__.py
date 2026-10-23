"""Egress and privacy (ADR-0018, M5 design 2026-10-23): the one way anything in `leafi/` reaches a cloud service.

Imports only `leafi.core`; `leafi.ops`, `leafi.devices`, `leafi.services` and `leafi.study` may import it, `leafi.core`
may not (design D1, `tests/test_architecture.py`).
"""
