"""Parent notifier (Bark and/or Telegram), through `leafi.privacy.egress` (ADR-0018 §2, M5 design D5).

`notify(counts)` is the study track's one parent notification, built from a fixed template: the learner's name
(sent as their surrogate, owner decision 2026-10-23) and integer counts; a guest, or a learner being forgotten,
is "a reader" (ADR-0021: no `cloud.text` any more). `send(text)` is the operational alert (ADR-0016): a catalog sentence, Telegram
only, purpose `ops`. Nothing else is sent; there is no frame parameter.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx

from leafi.core.ports import Counts

log = logging.getLogger("leafi.notifier")

TITLE = "Leafi: reading done"


class NotifierDevice:
    def __init__(self, name: str = "parent_phone", options: dict | None = None, settings=None) -> None:
        opts = options or {}
        self.name = name
        self.settings = settings
        self.bark_url = str(opts.get("bark_url") or "").rstrip("/")
        self.telegram_token = str(opts.get("telegram_bot_token") or "")
        self.telegram_chat = str(opts.get("telegram_chat_id") or "")
        self._egress = opts.get("egress")  # tests inject one; otherwise the process's

    def egress(self):
        if self._egress is None:
            from leafi.core.config import Settings
            from leafi.privacy import runtime

            self._egress = runtime.get(self.settings or Settings())
        return self._egress

    @property
    def configured(self) -> bool:
        return bool(self.bark_url or (self.telegram_token and self.telegram_chat))

    @property
    def can_send(self) -> bool:
        """Operational alerts go to Telegram only; Bark alone does not count."""
        return bool(self.telegram_token and self.telegram_chat)

    async def send(self, text: str) -> None:
        """Operational alert (ADR-0016): Telegram only, raises on a refusal, a transport error or a non-2xx reply
        so the deliverer can retry. Called only by `leafi/ops/alerts.py::deliver` with a catalog sentence."""
        from leafi.privacy.destinations import OPS
        from leafi.privacy.egress import Outgoing

        if not (self.telegram_token and self.telegram_chat):
            raise RuntimeError("telegram is not configured")
        e = self.egress()
        p = e.prepare("telegram", OPS, Outgoing(path=f"/bot{self.telegram_token}/sendMessage",
                                               form={"chat_id": self.telegram_chat, "text": text}))
        async with e.client("telegram", timeout=10) as c:
            r = await c.send(p.request())
            r.raise_for_status()

    def body(self, counts: Counts):
        """The template's one variable part besides the counts: who read (design D5)."""
        from leafi.privacy.egress import Text

        tail = (f" read: pages {counts.pages}, words read {counts.words_read}, words to practise "
                f"{counts.to_practise}, new items {counts.new_items}")
        if counts.learner_id is not None:
            e = self.egress()
            row = e._conn().execute("SELECT kind, forgetting, display_name FROM learners WHERE id=?",
                                    (counts.learner_id,)).fetchone()
            if row is not None and row[0] == "learner" and not row[1]:  # egress replaces the name (ADR-0021 E6)
                return Text(row[2] + tail, "derived_from_learner", (counts.learner_id,))
        return "A reader" + tail

    async def notify(self, counts: Counts) -> None:
        from leafi.privacy.egress import Outgoing, Refused

        log.info("notify: session %s", counts.session_id)
        if not self.configured:
            return
        e = self.egress()
        body = self.body(counts)
        kw = {"learner_id": counts.learner_id, "session_id": counts.session_id}
        if self.bark_url:
            base = urlsplit(self.bark_url).path.rstrip("/")
            try:
                p = e.prepare("bark", "notify", Outgoing(method="GET", path=base + "/{title}/{body}",
                                                         path_fields={"title": TITLE, "body": body}), **kw)
                async with e.client("bark", timeout=10) as c:
                    await c.send(p.request())
            except (httpx.HTTPError, Refused):
                log.error("bark notification failed", exc_info=True)
        if self.telegram_token and self.telegram_chat:
            try:
                text = body if isinstance(body, str) else type(body)(f"{TITLE}\n{body.value}", body.provenance,
                                                                       body.sources)
                p = e.prepare("telegram", "notify", Outgoing(path=f"/bot{self.telegram_token}/sendMessage",
                                                             form={"chat_id": self.telegram_chat, "text": text}),
                              **kw)
                async with e.client("telegram", timeout=10) as c:
                    await c.send(p.request())
            except (httpx.HTTPError, Refused):
                log.error("telegram notification failed", exc_info=True)
