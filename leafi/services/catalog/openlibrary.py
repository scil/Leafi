"""Open Library: `GET https://openlibrary.org/api/books?bibkeys=ISBN:<digits>&format=json&jscmd=data` → title,
through `leafi.privacy.egress` (purpose `catalog`, attributed to the session's learner or guest). Sends the ISBN
digits only. The books API answers directly; `/isbn/<digits>.json` answers with a redirect, which a study
purpose never follows (M5 design D16)."""

from __future__ import annotations

import re

import httpx

DESTINATION = "openlibrary"


class OpenLibrary:
    def __init__(self, settings=None, egress=None) -> None:
        self.settings = settings
        self._egress = egress

    def egress(self):
        if self._egress is None:
            from leafi.core.config import Settings
            from leafi.privacy import runtime

            self._egress = runtime.get(self.settings or Settings())
        return self._egress

    async def title_for_isbn(self, isbn: str) -> str | None:
        from leafi.privacy.egress import Outgoing, Refused

        digits = re.sub(r"[^0-9X]", "", isbn.upper())
        if not digits:
            return None
        e = self.egress()
        try:
            p = e.prepare(DESTINATION, "catalog", Outgoing(method="GET", path="/api/books", query={
                "bibkeys": f"ISBN:{digits}", "format": "json", "jscmd": "data"}))
            async with e.client(DESTINATION, timeout=10) as c:
                r = await c.send(p.request())
            if r.status_code != 200:
                return None
            title = (r.json().get(f"ISBN:{digits}") or {}).get("title")
            return str(title) if title else None
        except (httpx.HTTPError, ValueError, Refused):
            return None


def create(settings, egress=None) -> OpenLibrary:
    return OpenLibrary(settings, egress)


def status(settings) -> tuple[str, str]:
    return "ok", "cloud: sends ISBN digits to openlibrary.org"
