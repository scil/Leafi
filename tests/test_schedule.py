from agent.config import Settings


def test_parse_schedule():
    s = Settings(schedule=" water:07:20 , brush_pm:20:30 ")
    assert s.parsed_schedule() == [("water", "07:20"), ("brush_pm", "20:30")]


def test_parse_schedule_ignores_empty():
    s = Settings(schedule="water:07:20,,")
    assert s.parsed_schedule() == [("water", "07:20")]
