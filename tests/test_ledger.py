"""ADR-0017 §6.3: the ledger's counters are read from the rows the steps write (plan Decision log 2026-10-23)."""

from __future__ import annotations

from leafi.core.storage import Store
from leafi.study import miscues
from leafi.study.harness import rows
from leafi.study.harness.ledger import Ledger, Limits
from tests import seed


def test_counters_follow_the_rows(tmp_path):
    store = Store(tmp_path / "leafi.db")
    text = "The fox ran home."
    book, page, rev = seed.book_page(store, text)
    s = seed.session(store, book)
    read = seed.page_read(store, s, page, rev)
    first = rows.start_activity(store, session_id=s, kind="read_listen", cycle_id=None)
    cyc = rows.open_cycle(store, s, first)
    store.execute("UPDATE activities SET cycle_id=? WHERE id=?", (cyc, first))
    rows.start_activity(store, session_id=s, kind="read_listen", cycle_id=cyc, continuation=True)
    ledger = Ledger(store, s, Limits(max_errors=2, cards_max=3, activities_per_cycle=6, brain_calls=1.5))
    assert ledger.boundary_activities(cyc) == 1  # the continuation does not count
    for w in ("fox", "home"):
        mid = seed.miscue(store, read, rev, text, w)
        store.execute("UPDATE miscues SET cycle_id=? WHERE id=?", (cyc, mid))
        assert ledger.cycle_errors_left(cyc) == (2 if w == "fox" else 1)
        miscues.record_practice(store, mid, 1, "disagreed")
    assert ledger.cycle_errors_left(cyc) == 0
    cards = rows.start_activity(store, session_id=s, kind="add_cards", cycle_id=cyc)
    rows.finish_activity(store, cards, "completed", {"cards": 2})
    assert ledger.cards_left() == 1
    assert ledger.can_afford("standard") and not ledger.can_afford("deep")
    ledger.charge("standard")
    assert not ledger.can_afford("standard") and ledger.can_afford("fast")
