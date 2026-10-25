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
    """`run(BrainRequest)` is the v1 bridge (until M7e); `call(ModelRequest)` is the M7 port (design D5)."""

    name = "claude"
    locality_destination = DESTINATION
    host = "api.anthropic.com"

    def __init__(self, settings, client=None, egress=None, model: str | None = None) -> None:
        self.settings = settings
        self.model = model or settings.study_brain_model
        self.deadline_s = float(settings.brain_deadline_s)
        self._key = settings.anthropic_api_key
        self._client = client
        self._egress = egress
        self.needs_reset = False

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
            "messages": [{"role": "user", "content": Text(build_prompt(req), book=True)}],
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


    # ---------------------------------------------------------------- the M7 port (design D3, D5, D6)
    async def call(self, req):
        """Render, prepare through egress (with the model and the caller's budget), send through the
        mediating client; every outcome is a `CallRecord` (a cancellation propagates)."""
        import json
        import time

        from leafi.core.ports import CallRecord
        from leafi.privacy.egress import TOKEN_HEADER, Outgoing, Refused, Text
        from leafi.services.brain.render import messages_body

        if not self._key:
            return CallRecord("failed", model=req.model, detail="no ANTHROPIC_API_KEY")
        e = self.egress()

        def text(leaf):
            return Text(leaf.value, book=leaf.book)

        body = messages_body(req, req.turns, text)
        try:
            prepared = e.prepare(DESTINATION, req.purpose, Outgoing(path="/v1/messages", json=body),
                                 learner_id=req.learner_id, session_id=req.session_id, ttl_s=req.timeout_s + 1,
                                 model=req.model, budget=req.budget)
        except Refused as err:
            return CallRecord("refused", model=req.model, detail=str(err)[:120])
        req.attempt.sent, req.attempt.egress_attempt_id, req.attempt.model = prepared.json, prepared.attempt_id, \
            req.model
        started = time.monotonic()
        import anthropic

        try:
            msg = await self._client_for(req.timeout_s).messages.create(
                **prepared.json, extra_headers={TOKEN_HEADER: prepared.token_id})
        except anthropic.PermissionDeniedError as err:
            reason = _refusal(err)
            outcome = "over_budget" if reason == "over budget" else "refused"
            return self._record(outcome, req, prepared, started, detail=reason)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as err:
            return self._record("failed", req, prepared, started, detail=type(err).__name__)
        usage = getattr(msg, "usage", None)
        received = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        rec = self._record("ok", req, prepared, started, received=received, usage=usage,
                           stop_reason=getattr(msg, "stop_reason", None), model=getattr(msg, "model", req.model))
        if rec.stop_reason in ("refusal", "max_tokens"):
            rec.outcome, rec.detail = "invalid", ("refusal at ." if rec.stop_reason == "refusal" else "truncated at .")
            return rec
        try:
            rec.value = json.loads(prepared.reverse(received))
        except ValueError:
            rec.outcome, rec.detail = "invalid", "type at ."
        return rec

    def _client_for(self, timeout_s: float):
        """The SDK client on egress's mediating transport; its own timeout is a backstop behind the walk's."""
        client = self._get_client()
        return client.with_options(timeout=timeout_s + 1.0)

    def _record(self, outcome, req, prepared, started, *, received=None, usage=None, stop_reason=None, model=None,
                detail=""):
        import time

        from leafi.core.ports import CallRecord

        row = self.egress()._conn().execute("SELECT transmitted_attempts FROM egress_log WHERE id=?",
                                            (prepared.attempt_id,)).fetchone()
        return CallRecord(
            outcome, sent=prepared.json, received=received, model=model or req.model, provider="anthropic",
            tokens_in=int(getattr(usage, "input_tokens", 0) or 0), tokens_out=int(getattr(usage, "output_tokens", 0)
                                                                                  or 0),
            tokens_cached=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            latency_ms=int((time.monotonic() - started) * 1000), transmissions=int(row[0]) if row else 0,
            stop_reason=stop_reason, detail=detail)

    async def reset(self) -> None:
        """After a cut call: a connection being opened when a cancel lands can leak from the pool (libraries §2)."""
        client, self._client = self._client, None
        if client is not None:
            await client.close()


def _refusal(err) -> str:
    try:
        return str(err.response.json().get("refused", ""))[:120]
    except Exception:  # noqa: BLE001 - a 403 that is not egress's: just "refused"
        return "refused"


def create(settings, client=None, model: str | None = None) -> ClaudeBrain:
    return ClaudeBrain(settings, client, model=model)


def status(settings) -> tuple[str, str]:
    if not has_package("anthropic"):
        return "missing package", "uv pip install --python .venv anthropic==1.17.0"
    if not settings.anthropic_api_key:
        return "disabled", "ANTHROPIC_API_KEY empty: static Coach-voice phrases only"
    return "ok", f"model {settings.study_brain_model}"
