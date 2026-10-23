"""Early pytest plugin (`-p tests._alias_httpx`, pytest.ini): alias httpx to httpx2 before any test module or
plugin imports httpx, so the test fakes that patch `httpx` also see the `anthropic` SDK's traffic (TD-1)."""

import httpx2

httpx2.alias_httpx()
