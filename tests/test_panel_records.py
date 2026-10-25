"""Panel lines in the records (session panel design D8, step 5): each counted once into its activity's outcome on
every finish path, or into the session summary when no activity ran; the summary keeps each as its command and
fate, never its text; the Brain's view of the last activity gets the two counts and never the text. Real Store and Inputs,
scripted inputs; nothing speaks."""

from __future__ import annotations

from leafi.core.storage import loads
from leafi.core.text import typed_utterance
from leafi.study import controls
from leafi.study.brain import observe, sequence
from tests import harness_session as hsess
from tests.harness_world import make_world
from tests.test_do import run_activity

LINES = ["The fox ran home.", "It was late and dark."]


def panel(text: str):
    return typed_utterance(text, controls.PANEL)


def _outcomes(store, sid) -> list[tuple]:
    return [(r["kind"], r["status"], loads(r["outcome"], {})) for r in store.all(
        "SELECT kind, status, outcome FROM activities WHERE session_id=? ORDER BY id", (sid,))]


async def test_a_jumped_activity_counts_its_panel_lines_and_the_brain_sees_the_counts_only(settings):
    w = make_world(settings, settings, [panel("/say The fox ran home."), panel("/do break")])
    status, _, outcome = await run_activity(w, "read_listen", {"page": "current", "range": "rest"})
    assert status == "completed" and outcome["panel_inputs"] == 2 and outcome["ended_by"] == "do"
    data = sequence.gather(w.s, w, {"break", "end"}, ["break"])
    assert {k: data.last_activity[k] for k in ("kind", "panel_inputs", "ended_by")} == \
        {"kind": "read_listen", "panel_inputs": 2, "ended_by": "do"}
    sections = {sec.name: sec for sec in observe.observe(data).sections}
    (leaf,) = sections["last_activity"].leaves
    assert "panel_inputs=2" in leaf.value and "ended_by=do" in leaf.value
    assert not any("fox ran" in lf.value for sec in sections.values() if sec.name != "page" for lf in sec.leaves)


async def test_a_stopped_activity_still_counts_its_panel_line(settings):
    e = hsess.env(settings, [None, panel("/say The fox"), "/stop"], learner="Ada")
    sid = await hsess.run(e)
    ((kind, status, outcome),) = _outcomes(e.store, sid)
    assert (kind, status, outcome["panel_inputs"]) == ("read_listen", "stopped", 1)


async def test_panel_lines_at_a_boundary_go_to_the_summary_with_every_line_and_its_fate(settings):
    e = hsess.env(settings, [None, *LINES, panel("/say hello"), "/stop"], learner="Ada")
    sid = await hsess.run(e)
    summ = hsess.summary(e.store, sid)
    assert summ["panel_inputs_boundary"] == 1
    (line,) = summ["panel_lines"]
    assert line["command"] == "say" and line["activity_id"] is None and line["fate"] == "answered"
    assert "hello" not in str(summ)  # the summary holds enums and counts only, never the owner's text
    assert line["wall"]  # when, in wall time: the monotonic stamp means nothing after the process
    assert all("panel_inputs" not in o for _, _, o in _outcomes(e.store, sid))  # none ran inside an activity


async def test_a_session_without_panel_lines_records_nothing_new(settings):
    e = hsess.env(settings, [None, *LINES, "/stop"], learner="Ada")
    sid = await hsess.run(e)
    summ = hsess.summary(e.store, sid)
    assert "panel_lines" not in summ and "panel_inputs_boundary" not in summ
    assert all("panel_inputs" not in o and "ended_by" not in o for _, _, o in _outcomes(e.store, sid))
