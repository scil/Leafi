"""Book catalog lookup by ISBN (B1). Egress: Open Library receives ISBN digits only (ADR-0011);
`BOOK_LOOKUP=off` (default) disables it."""

from __future__ import annotations

from typing import Protocol

from leafi.services._registry import Registry

REGISTRY = Registry("catalog", {"openlibrary": "leafi.services.catalog.openlibrary",
                                "mock": "leafi.services.catalog.mock"})
LOOKUPS = ("off", *REGISTRY.backends)  # BOOK_LOOKUP values (runner.py: "off" disables the lookup)


class Catalog(Protocol):
    async def title_for_isbn(self, isbn: str) -> str | None: ...
