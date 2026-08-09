"""任务注册表自洽性:加新动作时,漏配的那一项会在这里炸出来。"""
import inspect

from agent import phrases, session
from agent.tasks import REGISTRY, TaskSpec, spec, title
from agent.vision.scorer import MotionScorer
from agent.vision.vlm import PROMPTS


def test_every_task_is_wired():
    knobs = set(inspect.signature(MotionScorer).parameters) - {"fps_hint"}
    for name, ts in REGISTRY.items():
        assert ts.name == name, "REGISTRY 的 key 必须与 TaskSpec.name 一致"
        assert ts.verify == "presence" or ts.verify in session.VERIFIERS
        assert name in phrases.TASKS, "新任务要在 phrases.py 配话术"
        if ts.verify in ("pose_dwell", "vlm_burst"):
            assert ts.vlm_kind in PROMPTS, "新任务要在 vlm.py 的 PROMPTS 加同名 key"
        if ts.verify == "pose_dwell":
            assert ts.scorer, "pose_dwell 必须显式给判据(anchor/axis 因动作而异,别吃默认值)"
            assert not (set(ts.scorer) - knobs), f"{name} 的 scorer 里有 MotionScorer 不认识的参数"


def test_unknown_task_falls_back_to_presence():
    ts = spec("feed_the_cat")
    assert ts.verify == "presence"
    assert title("feed_the_cat") == "feed_the_cat"


def test_spec_overrides_global_thresholds():
    default = spec("brush_pm")
    assert default.resolved_target() == 100  # 未覆盖 → 用 config 默认

    custom = TaskSpec(name="wash_hands", title="洗手", verify="pose_dwell",
                      vlm_kind="brush", target_seconds=25,
                      min_visible_seconds=20, inside_credit_cap=0)
    assert custom.resolved_target() == 25
    assert custom.resolved_min_visible() == 20
    assert custom.resolved_cap() == 0  # 0 是有效值,不能被当成"未设置"回退到全局
