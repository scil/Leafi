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

    @property
    def configured(self) -> bool:
        return bool(self.bark_url or (self.telegram_token and self.telegram_chat))

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
