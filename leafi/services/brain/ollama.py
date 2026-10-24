"""Ollama backend (local), through `leafi.privacy.egress`: the OpenAI-compatible `POST /v1/chat/completions`
(ADR-0018 §2, M5 design D17). `OLLAMA_URL`'s port is a gateway port, so the request needs egress's grant; a
local destination receives the text as it is (no pseudonymisation), which is what `LOCAL_MODELS` allows."""

from __future__ import annotations

import asyncio
import logging

import httpx

from leafi.services.brain import SCHEMAS, SYSTEM, BrainRequest, build_prompt, parse_json, validate

log = logging.getLogger("leafi.brain.ollama")

DESTINATION = "ollama"


class OllamaBrain:
    def __init__(self, settings, egress=None) -> None:
        self.settings = settings
        self.model = settings.brain_local_model or "qwen3:8b"
        self.deadline_s = float(settings.brain_deadline_s)
        self._egress = egress

    def egress(self):
        if self._egress is None:
            from leafi.privacy import runtime

            self._egress = runtime.get(self.settings)
        return self._egress

    async def run(self, req: BrainRequest) -> dict | None:
        from leafi.privacy.egress import Outgoing, Refused, Text

        body = {"model": self.model, "stream": False,
                "response_format": {"type": "json_schema", "json_schema": {"name": req.intent.value,
                                                                           "schema": SCHEMAS[req.intent]}},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": Text(build_prompt(req), "page")}]}
        e = self.egress()
        try:
            p = e.prepare(DESTINATION, "generate", Outgoing(path="/v1/chat/completions", json=body),
                          learner_id=req.learner_id, session_id=req.session_id, ttl_s=self.deadline_s)
        except Refused as err:
            log.info("local brain request refused by egress: %s", err)
            return None
        try:
            async with e.client(DESTINATION, timeout=self.deadline_s) as c:
                r = await asyncio.wait_for(c.send(p.request()), self.deadline_s)
            r.raise_for_status()
            content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return validate(req.intent, parse_json(content))
        except (httpx.HTTPError, TimeoutError, ValueError, IndexError):
            return None


def create(settings, egress=None) -> OllamaBrain:
    return OllamaBrain(settings, egress)


def status(settings) -> tuple[str, str]:
    if not settings.brain_local_model:
        return "deferred", "Ollama fallback deferred in v1 (ADR-0011)"
    return "ok", f"{settings.ollama_url} model {settings.brain_local_model} (not probed)"
