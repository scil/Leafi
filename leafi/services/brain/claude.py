"""Claude backend (cloud, text only), through `leafi.privacy.egress` (ADR-0018 §2, M5 design D17).

SDK: `anthropic` 1.17.0 on `httpx2` (TD-1; 2.x moves to API version 2026-10-21 and is a separate step). Every
request is prepared by egress first — the page window and candidates as `page` text, the counts as `system` —
so protected names are replaced and the attempt is logged; the SDK's client is egress's mediating client, so a
request egress did not prepare cannot leave. The one retry belongs to the mediator (a connect error or a 5xx);
the client never retries (`max_retries=0`) and never traces (`open_telemetry=False`). Fallback is
application-owned: an empty key, a refusal, a timeout or an invalid reply all return None and the session uses
static phrases. `anthropic` is imported on first use.
"""

from __future__ import annotations

import asyncio
import logging

from leafi.services._registry import has_package
from leafi.services.brain import SCHEMAS, SYSTEM, BrainRequest, Intent, build_prompt, parse_json, validate

log = logging.getLogger("leafi.brain.claude")

DESTINATION = "anthropic"
PURPOSE = {Intent.EXPLAIN_WORD: "generate", Intent.EXPLAIN_SENTENCE: "generate", Intent.QUESTIONS: "generate",
           Intent.ENCOURAGE: "word"}


class ClaudeBrain:
    def __init__(self, settings, client=None, egress=None) -> None:
        self.settings = settings
        self.model = settings.study_brain_model
        self.deadline_s = float(settings.brain_deadline_s)
        self._key = settings.anthropic_api_key
        self._client = client
        self._egress = egress

    def egress(self):
        if self._egress is None:
            from leafi.privacy import runtime

            self._egress = runtime.get(self.settings)
        return self._egress

    def _get_client(self):
        if self._client is None:
            import anthropic  # lazy

            e = self.egress()
            dest = e.registry[DESTINATION]
            host = sorted(dest.hosts)[0]
            default = 443 if dest.scheme == "https" else 80
            base = f"{dest.scheme}://{host}" + ("" if dest.port == default else f":{dest.port}")
            self._client = anthropic.AsyncAnthropic(api_key=self._key, base_url=base, max_retries=0,
                                                    timeout=self.deadline_s, open_telemetry=False,
                                                    http_client=e.client(DESTINATION))
        return self._client

    def request_params(self, req: BrainRequest) -> dict:
        from leafi.privacy.egress import Text

        return {
            "model": self.model,
            "max_tokens": 4096,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": Text(build_prompt(req), "page")}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMAS[req.intent]}},
        }

    async def run(self, req: BrainRequest) -> dict | None:
        if not self._key:
            return None
        from leafi.privacy.egress import TOKEN_HEADER, Outgoing, Refused

        try:
            prepared = self.egress().prepare(DESTINATION, PURPOSE[req.intent],
                                             Outgoing(path="/v1/messages", json=self.request_params(req)),
                                             learner_id=req.learner_id, session_id=req.session_id,
                                             ttl_s=self.deadline_s, model=self.model)
        except Refused as e:
            log.info("brain request refused by egress: %s", e)
            return None
        try:
            msg = await asyncio.wait_for(self._get_client().messages.create(
                **prepared.json, extra_headers={TOKEN_HEADER: prepared.token_id}), self.deadline_s)
        except TimeoutError:
            log.warning("brain deadline reached")
            return None
        except Exception as e:  # SDK errors (a refusal is a 403): no adapter retry, the mediator owns it
            log.warning("brain call failed: %s", type(e).__name__)
            return None
        if getattr(msg, "stop_reason", None) == "refusal":
            return None
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        data = validate(req.intent, parse_json(prepared.reverse(text)))
        if data is None:
            log.warning("brain reply dropped: schema or action not allowed")
        return data


def create(settings, client=None) -> ClaudeBrain:
    return ClaudeBrain(settings, client)


def status(settings) -> tuple[str, str]:
    if not has_package("anthropic"):
        return "missing package", "uv pip install --python .venv anthropic==1.17.0"
    if not settings.anthropic_api_key:
        return "disabled", "ANTHROPIC_API_KEY empty: static Coach-voice phrases only"
    return "ok", f"model {settings.study_brain_model}"
