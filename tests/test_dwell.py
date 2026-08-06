from agent.vision.dwell import InsideTracker


def ev(etype: str, zones=()):
    return {"type": etype, "after": {"label": "person", "current_zones": list(zones)}}


def test_enter_and_exit():
    tr = InsideTracker()
    tr.on_event(ev("end", ["bathroom_door"]), now=100.0)  # 在门口消失 = 进门
    tr.on_event(ev("new"), now=130.0)                      # 再次出现 = 出来了
    assert tr.finalize(140.0) == 30.0


def test_open_interval_counted_at_finalize():
    tr = InsideTracker()
    tr.on_event(ev("end", ["bathroom_door"]), now=100.0)
    assert tr.finalize(150.0) == 50.0


def test_disappear_elsewhere_not_counted():
    tr = InsideTracker()
    tr.on_event(ev("end", ["hallway"]), now=100.0)  # 不在门口消失 ≠ 进门
    assert tr.finalize(200.0) == 0.0


def test_non_person_ignored():
    tr = InsideTracker()
    tr.on_event({"type": "end", "after": {"label": "car", "current_zones": ["bathroom_door"]}}, 100.0)
    assert tr.finalize(200.0) == 0.0


def test_entered_zones_also_counts():
    tr = InsideTracker()
    tr.on_event({"type": "end", "after": {"label": "person", "entered_zones": ["bathroom_door"]}}, 10.0)
    tr.on_event(ev("new"), now=25.0)
    assert tr.finalize(30.0) == 15.0
