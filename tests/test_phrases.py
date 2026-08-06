from agent import phrases


def test_all_tasks_have_core_kinds():
    for task in phrases.TASKS:
        for kind in ("opening", "retry", "arrived"):
            assert phrases.pick(task, kind)
        assert phrases.title(task)


def test_generic_fallback():
    assert phrases.pick("brush_am", "milestone")  # brush_am 无 milestone → 走 GENERIC
    assert phrases.pick("unknown_task", "unknown_kind")  # 双未知也不崩
