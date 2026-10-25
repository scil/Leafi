"""The session panel's snapshot (session panel design D3, step 4): taken through the harness hooks during real
sessions, it reads no database, is plain JSON, and shows the activity, the reading, the boundary, the want and each
panel line's fate. Real Store and Inputs, scripted inputs; nothing speaks."""

from __future__ import annotations

import json
import time

from leafi.core.text import typed_utterance
from leafi.study import controls
from leafi.study.harness.latch import Want
from leafi.study.harness.snapshot import snapshot
from leafi.study.harness.world import reading_counts
from tests import harness_session as hsess
from tests.harness_world import make_world, run


class NoStore:
    """Any use of the store during a snapshot fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"the snapshot used the store ({name})")


def _record(e, shots: list) -> None:
    """Snapshot on every harness and input change, with the store taken away while it runs."""

    def built(s, w):
        def take():
            real = s.store, w.store
            s.store = w.store = NoStore()
            try:
                shots.append(json.loads(json.dumps(snapshot(s, w))))  # plain JSON, no object escapes
            finally:
                s.store, w.store = real

        s.hooks.append(take)
        w.inputs.on_change = take

    e.on_built = built


async def test_a_session_is_seen_from_its_first_boundary_to_its_end_without_the_store(settings):
    shots: list = []
    e = hsess.env(settings, [None, "The fox ran home.", "It was late", "/stop"], learner="Ada")
    _record(e, shots)
    await hsess.run(e)
    assert shots
    assert shots[-1]["learner"] == {"kind": "learner", "name": "Ada"}
    assert any("break" in sh["boundary"]["menu"] for sh in shots)  # a boundary was seen with its menu
    reading = [sh for sh in shots if sh["activity"] and sh["activity"]["kind"] == "read_listen"]
    assert reading and reading[0]["book"]["title"] == "Fixture" and reading[-1]["page"]["printed"] == 1
    mid = next(sh for sh in reading if sh["reading"] and sh["reading"]["sentences"]["completed"] == 1)
    assert mid["reading"]["sentences"]["total"] == 2
    assert [t["text"] for t in mid["reading"]["current_sentence"]] == ["It", "was", "late", "and", "dark"]
    assert any(sh["io"]["listening"] for sh in reading)
    last = shots[-1]
    assert last["activities"][0]["kind"] == "read_listen" and last["activities"][0]["status"] == "stopped"
    assert last["io"]["accepting"] is False  # the body ended


async def test_a_panel_do_is_logged_with_its_fate_and_shown_while_it_waits(settings):
    shots: list = []
    panel = typed_utterance("/do break", controls.PANEL)
    e = hsess.env(settings, [None, "The fox ran", panel, "/stop"], learner="Ada")
    _record(e, shots)
    await hsess.run(e)
    pending = [sh["want"] for sh in shots if sh["want"]]
    assert pending and pending[0]["kind"] == "break" and pending[0]["source"] == "panel"
    (entry,) = shots[-1]["panel_log"]
    assert entry["line"] == "/do break" and entry["fate"] == "switched" and entry["activity_id"] is not None
    kinds = [(a["kind"], a["params"].get("by")) for a in shots[-1]["activities"]]
    assert kinds == [("read_listen", None), ("break", "panel")]


async def test_a_panel_lines_fate_follows_it(settings):
    shots: list = []
    e = hsess.env(settings, [None, typed_utterance("/say The fox", controls.PANEL),
                             typed_utterance("/do flying", controls.PANEL), "/stop"], learner="Ada")
    _record(e, shots)
    await hsess.run(e)
    fates = [(x["line"], x["fate"]) for x in shots[-1]["panel_log"]]
    assert fates == [("/say The fox", "answered"), ("/do flying", "want_refused")]


def test_what_a_want_waits_for(settings):
    w = make_world(settings, settings, [])
    s, io = w.s, w.inputs
    s.latch.post_want(Want("break", "panel", None, time.monotonic()))
    assert snapshot(s, w)["want"]["waiting_for"] == "setup"  # no boundary yet
    s.boundary.menu = frozenset({"break", "end"})
    assert snapshot(s, w)["want"]["waiting_for"] == "step"
    io.speaking = True
    assert snapshot(s, w)["want"]["waiting_for"] == "speech"
    io._waiting = 1  # a Brain call, while the filler speaks
    assert snapshot(s, w)["want"]["waiting_for"] == "brain"


async def test_practice_settles_the_token_in_the_worlds_reading_state_too(settings):
    w = make_world(settings, settings, ["The fax ran home.", "It was late and dark.", "/skip"])
    await run(w, "read_listen", {"page": "next"})
    assert reading_counts(w.state)["candidate"] == 1
    mid = w.store.one("SELECT id FROM miscues WHERE expected='fox'")["id"]
    await run(w, "practise_errors", {"candidate_ids": [mid]})
    assert reading_counts(w.state)["candidate"] == 0 and reading_counts(w.state)["settled"] == 1
