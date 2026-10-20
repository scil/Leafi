"""Open Library: `GET https://openlibrary.org/isbn/<digits>.json` → title. Sends the ISBN digits only."""

from __future__ import annotations

import re

import httpx


class OpenLibrary:
    def __init__(self, settings=None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def title_for_isbn(self, isbn: str) -> str | None:
        digits = re.sub(r"[^0-9X]", "", isbn.upper())
        if not digits:
            return None
        try:
            async with httpx.AsyncClient(timeout=10, transport=self._transport, follow_redirects=True) as c:
                r = await c.get(f"https://openlibrary.org/isbn/{digits}.json")
            if r.status_code != 200:
                return None
            title = r.json().get("title")
            return str(title) if title else None
        except (httpx.HTTPError, ValueError):
            return None


def create(settings, transport=None) -> OpenLibrary:
    return OpenLibrary(settings, transport)


def status(settings) -> tuple[str, str]:
    return "ok", "cloud: sends ISBN digits to openlibrary.org"
