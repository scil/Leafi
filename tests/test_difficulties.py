"""ADR-0013 → Difficulties (amended by ADR-0017 §8.6): `unsure` counts 0.3 only with reason `disagreed` or `idle`;
`not_practised`, `skipped`, `interrupted` and `unclear` contribute 0 and do not count toward the existence rule."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store
from leafi.study import knowledge
from tests import seed

TEXT = "The fox ran home."


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _unsure_in_sessions(store, reason: str, n: int) -> None:
    book, page, rev = seed.book_page(store, TEXT)
    for _ in range(n):
        s = seed.session(store, book)
        read = seed.page_read(store, s, page, rev)
        seed.miscue(store, read, rev, TEXT, "fox", status="unsure", reason=reason)


@pytest.mark.parametrize("reason", ["not_practised", "skipped", "interrupted", "unclear"])
def test_reasons_that_are_no_evidence_never_make_a_row(store, reason):
    _unsure_in_sessions(store, reason, 4)
    knowledge.recompute_difficulties(store, seed.learner(store))
    assert store.all("SELECT * FROM difficulties") == []


@pytest.mark.parametrize("reason", ["disagreed", "idle"])
def test_disagreed_and_idle_in_three_sessions_make_a_watch_row(store, reason):
    _unsure_in_sessions(store, reason, 3)
    knowledge.recompute_difficulties(store, seed.learner(store))
    row = store.one("SELECT kind, weight FROM difficulties WHERE miscue_key='fox'")
    assert row["kind"] == "watch" and row["weight"] == pytest.approx(0.9, abs=0.01)
