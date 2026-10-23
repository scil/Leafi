"""ADR-0017 §6.1: speech inside `read_listen` follows `reading.interrupt`; a supplied word is a candidate."""

from __future__ import annotations

from tests.fakes import ScriptedListener
from tests.harness_world import make_world, run

STUCK = ["The fox", None, None, None, None, None, "yes", "home.", "It was late and dark."]


async def test_stuck_only_offers_a_hint_and_a_yes_supplies_the_word(settings):
    w = make_world(settings, settings, [], listener=ScriptedListener(STUCK, voice=True))
    status, _, _ = await run(w, "read_listen", {"page": "next"})
    assert status == "completed"
    assert "Want a hint?" in w.face.texts and 'It says "ran".' in w.face.texts
    row = w.store.one("SELECT origin, status FROM miscues WHERE expected='ran'")
    assert (row["origin"], row["status"]) == ("supplied", "candidate")  # a told word is an error (ADR-0013)


async def test_never_says_nothing_inside_reading(settings):
    script = ["The fox", None, None, None, None, None, None, "ran home.", "It was late and dark."]
    w = make_world(settings, settings, [], listener=ScriptedListener(script, voice=True),
                   values={"reading.interrupt": "never"})
    status, _, _ = await run(w, "read_listen", {"page": "next"})
    assert status == "completed"
    page_ready = [t for t in w.face.texts if t.startswith("Page") or t.startswith("Got page")]
    assert w.face.texts == page_ready  # nothing but the announcement
    assert w.store.one("SELECT COUNT(*) AS n FROM miscues")["n"] == 0


async def test_a_hint_is_offered_once_per_place(settings):
    script = ["The fox", None, None, None, None, None, "no", None, None, None, None, None, "ran home.",
              "It was late and dark."]
    w = make_world(settings, settings, [], listener=ScriptedListener(script, voice=True))
    await run(w, "read_listen", {"page": "next"})
    assert w.face.texts.count("Want a hint?") == 1
