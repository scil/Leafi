"""Claude backend (cloud, text only). Egress: api.anthropic.com with the BrainRequest payload only (ADR-0011).

SDK: `anthropic` 0.120.2 (TD-1) has `output_config.format` (json_schema structured outputs) but no
`fallbacks`, so fallback is application-owned: an empty key, a refusal, a timeout or an invalid reply all
return None and the session uses static phrases. Deadline `BRAIN_DEADLINE_S` (12 s) overall, one retry.
`anthropic` is imported on first use.
"""

from __future__ import annotations

import asyncio
import logging

from leafi.services._registry import has_package
from leafi.services.brain import SCHEMAS, SYSTEM, BrainRequest, build_prompt, parse_json, validate

log = logging.getLogger("leafi.brain.claude")


class ClaudeBrain:
    def __init__(self, settings, client=None) -> None:
        self.model = settings.brain_model
        self.deadline_s = float(settings.brain_deadline_s)
        self._key = settings.anthropic_api_key
        self._client = client

    def _get_client(self):
        if self._client is None:
            import anthropic  # lazy

            self._client = anthropic.AsyncAnthropic(api_key=self._key, max_retries=0, timeout=self.deadline_s)
        return self._client

    def request_params(self, req: BrainRequest) -> dict:
        return {
            "model": self.model,
            "max_tokens": 4096,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": build_prompt(req)}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMAS[req.intent]}},
        }

    async def run(self, req: BrainRequest) -> dict | None:
        if not self._key:
            return None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.deadline_s
        params = self.request_params(req)
        for attempt in (1, 2):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(self._get_client().messages.create(**params), remaining)
            except TimeoutError:
                log.warning("brain deadline reached (attempt %d)", attempt)
                break
            except Exception as e:  # SDK errors: retry once inside the deadline, then give up
                log.warning("brain call failed (attempt %d): %s", attempt, type(e).__name__)
                continue
            if getattr(msg, "stop_reason", None) == "refusal":
                return None
            text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
            data = validate(req.intent, parse_json(text))
            if data is not None:
                return data
            log.warning("brain reply dropped: schema or action not allowed")
        return None


def create(settings, client=None) -> ClaudeBrain:
    return ClaudeBrain(settings, client)


def status(settings) -> tuple[str, str]:
    if not has_package("anthropic"):
        return "missing package", "uv pip install --python .venv anthropic==0.120.2"
    if not settings.anthropic_api_key:
        return "disabled", "ANTHROPIC_API_KEY empty: static Coach-voice phrases only"
    return "ok", f"model {settings.brain_model}"
