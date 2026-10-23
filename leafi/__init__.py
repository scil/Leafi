"""Leafi: a household AI agent with a hardware-agnostic core and tracks (ADR-0001)."""

import httpx2

# TD-1 (ADR-0017 §10): every `import httpx` in this process - Leafi's own clients, the test fakes, and
# libraries still on httpx - resolves to httpx2, the HTTP layer of `anthropic` >= 1, so one transport
# family carries all traffic. It must run before anything imports httpx (RuntimeError otherwise); a second
# call (agent/__init__.py, the pytest plugin) is a no-op.
httpx2.alias_httpx()
