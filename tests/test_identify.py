"""ADR-0018 §1 identification (minimal form, no recognition) and the guest end-state table (plan M6.5)."""

from __future__ import annotations

from leafi.core.storage import Store, loads
from leafi.study.harness import guests
from tests import seed
from tests.harness_session import env, run


def _owner(store, sid):
    return store.one("SELECT l.id, l.kind, l.display_name, l.guest_reason, l.guest_expires_at FROM reading_sessions s "
                     "JOIN learners l ON l.id = s.learner_id WHERE s.id=?", (sid,))


async def test_a_known_name_is_confirmed_and_adopted_and_the_guest_row_goes(settings):
    store = Store(settings.db_path)
    seed.learner(store, "Ada")
    sid = await run(env(settings, ["it's adah", "yes", "/stop"]))  # fuzzy ≥ 0.85
    assert _owner(store, sid)["display_name"] == "Ada"
    assert store.one("SELECT COUNT(*) AS n FROM learners WHERE kind='guest'")["n"] == 0


async def test_a_console_pick_by_number(settings):
    store = Store(settings.db_path)
    seed.learner(store, "Ada")
    seed.learner(store, "Ben")
    e = env(settings, ["2", "yes", "/stop"])
    sid = await run(e)
    assert _owner(store, sid)["display_name"] == "Ben"
    assert any("1. Ada, 2. Ben" in t for t in e.face.texts)


async def test_a_new_name_is_enrolled_after_a_yes(settings):
    store = Store(settings.db_path)
    sid = await run(env(settings, ["My name is Cleo", "yes", "/stop"]))
    o = _owner(store, sid)
    assert (o["display_name"], o["kind"]) == ("Cleo", "learner")


async def test_a_new_learner_is_asked_for_a_school(settings):
    from leafi.privacy import settings as privacy

    store = Store(settings.db_path)
    sid = await run(env(settings, ["I'm Cleo", "yes", "I go to Oakwood Primary", "/stop"]))
    p = privacy.read(store, _owner(store, sid)["id"])
    assert privacy.school_name(store, p) == "Oakwood Primary"
    sid = await run(env(settings, ["I'm Dan", "yes", "no school", "/stop"]))
    assert privacy.read(store, _owner(store, sid)["id"]).school == "none"
    sid = await run(env(settings, ["I'm Eve", "yes", "I don't know", "/stop"]))
    eve = _owner(store, sid)["id"]
    assert privacy.read(store, eve).school is None and not privacy.read(store, eve).cloud_text_allowed


def test_parse_school():
    from leafi.core.ports import Utterance
    from leafi.study.harness.identify import parse_school

    def p(text):
        return parse_school(Utterance(text=text, words=[], typed=False) if text is not None else None)

    assert p("It's St. Mary's.") == ("school", "St. Mary's")
    assert p("my school is 实验小学") == ("school", "实验小学")
    assert p("No") == p("I don’t go to school") == p("homeschooled") == ("none", None)
    assert p(None) is p("") is p("not sure") is p("yes") is None


async def test_declined_deletes_the_guests_rows_and_keeps_the_counts_under_anonymous(settings):
    store = Store(settings.db_path)
    sid = await run(env(settings, ["don't remember me", None, "The fox ran home.", "It was late and dork.", "/stop"]))
    o = _owner(store, sid)
    assert o["kind"] == "anonymous"
    assert store.one("SELECT COUNT(*) AS n FROM learners WHERE kind='guest'")["n"] == 0
    assert store.one("SELECT COUNT(*) AS n FROM miscues")["n"] == 0
    assert store.one("SELECT COUNT(*) AS n FROM utterances")["n"] == 0
    summ = loads(store.one("SELECT summary FROM reading_sessions WHERE id=?", (sid,))["summary"])
    assert summ["guest"] == "deleted" and summ["candidates"] == 1  # counts only


async def test_unconfirmed_is_kept_until_expiry_and_zero_days_deletes_at_wrap(settings):
    store = Store(settings.db_path)
    sid = await run(env(settings, [None, None, "/stop"]))  # two attempts without a name
    o = _owner(store, sid)
    assert (o["kind"], o["guest_reason"]) == ("guest", "unconfirmed") and o["guest_expires_at"]
    settings.guest_keep_days = 0
    sid2 = await run(env(settings, [None, None, "/stop"]))
    assert _owner(store, sid2)["kind"] == "anonymous"


async def test_a_terminal_before_identify_returned_normalises_to_unconfirmed(settings):
    store = Store(settings.db_path)
    sid = await run(env(settings, ["/stop"]))
    o = _owner(store, sid)
    assert (o["kind"], o["guest_reason"]) == ("guest", "unconfirmed") and o["guest_expires_at"]


def test_the_sweep_deletes_expired_guests_with_no_open_session(tmp_path):
    store = Store(tmp_path / "leafi.db")
    old = guests.new_guest(store)
    book, _, _ = seed.book_page(store, "The fox.")
    s_old = seed.session(store, book, learner_id=old)
    store.execute("UPDATE reading_sessions SET ended_at='2026-01-02T00:00:00+00:00' WHERE id=?", (s_old,))
    guests.set_guest(store, old, "unconfirmed", "2026-01-01T00:00:00+00:00")
    open_ = guests.new_guest(store)
    seed.session(store, book, learner_id=open_)  # still running
    guests.set_guest(store, open_, "declined")
    assert guests.sweep(store) == []  # ended but still delivering: its egress is not over (M5 design D5)
    store.execute("UPDATE reading_sessions SET post_done_at='2026-01-02T00:00:01+00:00' WHERE id=?", (s_old,))
    assert guests.sweep(store) == [old]
    assert store.one("SELECT learner_id FROM reading_sessions WHERE id=?", (s_old,))["learner_id"] == \
        guests.anonymous(store)
    assert guests.sweep(store) == []


async def test_a_learner_being_forgotten_is_never_adopted(settings):
    store = Store(settings.db_path)
    ada = seed.learner(store, "Ada")
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (ada,))
    sid = await run(env(settings, ["Ada", "yes", "Ada", "yes", "/stop"]))
    assert _owner(store, sid)["display_name"] != "Ada" or _owner(store, sid)["id"] != ada
