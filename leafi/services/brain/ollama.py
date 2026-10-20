"""Ollama backend (local, deferred in v1 by ADR-0011; written as a thin `POST /api/chat`)."""

from __future__ import annotations

import asyncio

import httpx

from leafi.services.brain import SCHEMAS, SYSTEM, BrainRequest, build_prompt, parse_json, validate


class OllamaBrain:
    def __init__(self, settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = settings.ollama_url.rstrip("/")
        self.model = settings.brain_local_model or "qwen3:8b"
        self.deadline_s = float(settings.brain_deadline_s)
        self._transport = transport

    async def run(self, req: BrainRequest) -> dict | None:
        body = {"model": self.model, "stream": False, "format": SCHEMAS[req.intent],
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": build_prompt(req)}]}
        try:
            async with httpx.AsyncClient(timeout=self.deadline_s, transport=self._transport) as c:
                r = await asyncio.wait_for(c.post(f"{self.url}/api/chat", json=body), self.deadline_s)
            r.raise_for_status()
            return validate(req.intent, parse_json(r.json().get("message", {}).get("content", "")))
        except (httpx.HTTPError, TimeoutError, ValueError):
            return None


def create(settings, transport=None) -> OllamaBrain:
    return OllamaBrain(settings, transport)


def status(settings) -> tuple[str, str]:
    if not settings.brain_local_model:
        return "deferred", "Ollama fallback deferred in v1 (ADR-0011)"
    return "ok", f"{settings.ollama_url} model {settings.brain_local_model} (not probed)"
