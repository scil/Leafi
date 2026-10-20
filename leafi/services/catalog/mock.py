"""Mock catalog: a fixed ISBN → title table."""

from __future__ import annotations


class MockCatalog:
    def __init__(self, titles: dict[str, str] | None = None) -> None:
        self.titles = titles or {}
        self.asked: list[str] = []

    async def title_for_isbn(self, isbn: str) -> str | None:
        self.asked.append(isbn)
        return self.titles.get(isbn)


def create(settings, titles: dict[str, str] | None = None) -> MockCatalog:
    return MockCatalog(titles)
