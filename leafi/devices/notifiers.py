"""Parent notifier (Bark and/or Telegram). Text only (ADR-0011): the port has no frame parameter.

Egress: `api.day.app` (or the configured Bark host) and `api.telegram.org`, text only
(docs/architecture/quality-attributes/security.md).
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

log = logging.getLogger("leafi.notifier")


class NotifierDevice:
    def __init__(self, name: str = "parent_phone", options: dict | None = None, settings=None) -> None:
        opts = options or {}
        self.name = name
        self.bark_url = str(opts.get("bark_url") or "").rstrip("/")
        self.telegram_token = str(opts.get("telegram_bot_token") or "")
        self.telegram_chat = str(opts.get("telegram_chat_id") or "")
        self._transport = opts.get("transport")  # tests inject an httpx.MockTransport

    @property
    def configured(self) -> bool:
        return bool(self.bark_url or (self.telegram_token and self.telegram_chat))

    @property
    def can_send(self) -> bool:
        """Operational alerts go to Telegram only; Bark alone does not count."""
        return bool(self.telegram_token and self.telegram_chat)

    async def send(self, text: str) -> None:
        """Operational alert (ADR-0016): Telegram only, raises on a transport error or a non-2xx reply so the
        deliverer can retry. Called only by `leafi/ops/alerts.py::deliver` with a catalog sentence."""
        if not (self.telegram_token and self.telegram_chat):
            raise RuntimeError("telegram is not configured")
        async with httpx.AsyncClient(timeout=10, transport=self._transport) as c:
            r = await c.post(f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                             data={"chat_id": self.telegram_chat, "text": text})
            r.raise_for_status()

    async def notify(self, title: str, body: str) -> None:
        log.info("notify: %s", title)
        if not self.configured:
            return
        async with httpx.AsyncClient(timeout=10) as c:
            if self.bark_url:
                try:
                    await c.get(f"{self.bark_url}/{quote(title)}/{quote(body or ' ')}")
                except httpx.HTTPError:
                    log.error("bark notification failed", exc_info=True)
            if self.telegram_token and self.telegram_chat:
                try:
                    await c.post(f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                                 data={"chat_id": self.telegram_chat, "text": f"{title}\n{body}"})
                except httpx.HTTPError:
                    log.error("telegram notification failed", exc_info=True)
