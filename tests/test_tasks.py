"""任务注册表:加新动作时,漏配的那一项会在这里炸出来;配置文件的读写与校验也在这里锁住。"""
import agent.tasks as T
import pytest
from agent import phrases, session
from agent.tasks import TaskSpec, all_specs, spec, title, validate, validate_all
from agent.vision.vlm import PROMPTS


def _brush() -> TaskSpec:
    return TaskSpec(
        name="wash_hands",
        title="饭前洗手",
        verify="pose_dwell",
        schedule="11:50",
        vlm_kind="wash",
        prompt="判断是否在洗手。只判断动作,不要识别或猜测人物身份。",
        scorer={"anchor": "hip", "axis": "x", "near_k": 1.5},
        target_seconds=25,
        min_visible_seconds=20,
        inside_credit_cap=0,
        milestones=(10, 20),
        phrases={"opening": ["去洗手"], "retry": ["还没洗"], "arrived": ["开搓"]},
    )


# ---------- 仓库里那份 config/tasks.yml 必须自洽 ----------

def test_shipped_config_is_valid():
    assert validate_all(all_specs()) == {}


def test_every_task_is_wired():
    for ts in all_specs():
        assert ts.verify == "presence" or ts.verify in session.VERIFIERS
        if ts.verify in ("pose_dwell", "vlm_burst"):
            # 提问优先用 spec 自带的,留空才回退 vlm.PROMPTS——两者至少有一个
            assert ts.prompt or ts.vlm_kind in PROMPTS
        if ts.verify == "pose_dwell":
            assert ts.scorer, "pose_dwell 必须显式给判据(anchor/axis 因动作而异)"


def test_unknown_task_falls_back_to_presence():
    ts = spec("feed_the_cat")
    assert ts.verify == "presence"
    assert title("feed_the_cat") == "feed_the_cat"


def test_phrases_prefer_spec_over_static():
    assert phrases.pick("brush_pm", "opening")          # 来自 tasks.yml
    assert phrases.pick("brush_am", "milestone")        # 未配 → GENERIC 兜底
    assert phrases.pick("unknown_task", "unknown_kind")  # 双未知也不崩


# ---------- 阈值解析 ----------

def test_spec_overrides_global_thresholds():
    assert spec("brush_pm").resolved_target() == 100     # 未覆盖 → config 默认
    w = _brush()
    assert w.resolved_target() == 25
    assert w.resolved_min_visible() == 20
    assert w.resolved_cap() == 0  # 0 是有效值,不能被当成"未设置"回退到全局


# ---------- 校验规则 ----------

@pytest.mark.parametrize(
    "patch, hit",
    [
        ({"name": "Wash Hands"}, "小写字母"),
        ({"title": " "}, "标题"),
        ({"verify": "magic"}, "验证策略"),
        ({"schedule": "25:00"}, "HH:MM"),
        ({"phrases": {"retry": ["x"], "arrived": ["y"]}}, "opening"),
        ({"prompt": "他是谁?在洗手吗?"}, "红线"),
        ({"scorer": {}}, "计分判据"),
        ({"scorer": {"anchor": "hip", "min_flip_per_s": 1}}, "不认识的参数"),
        ({"scorer": {"anchor": "elbow", "axis": "x"}}, "anchor"),
        ({"min_visible_seconds": 99}, "不能大于"),
        ({"milestones": (20, 10)}, "递增"),
        ({"milestones": (10, 99)}, "永远播不出来"),
    ],
)
def test_validate_catches(patch, hit):
    from dataclasses import replace

    errs = validate(replace(_brush(), **patch))
    assert any(hit in e for e in errs), f"{patch} 应该报「{hit}」,实际:{errs}"


def test_validate_accepts_a_good_spec():
    assert validate(_brush()) == []


def test_duplicate_names_rejected():
    errs = validate_all([_brush(), _brush()])
    assert any("重复" in e for e in errs["wash_hands"])


# ---------- 读写往返 ----------

def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "TASKS_FILE", tmp_path / "tasks.yml")
    monkeypatch.setattr(T, "_cache", {})
    monkeypatch.setattr(T, "_cache_mtime", None)

    T.save([_brush()])
    back = T.all_specs()
    assert len(back) == 1
    assert back[0] == _brush(), "存进去什么样,读出来就该什么样"
    assert T.scheduled() == [("wash_hands", "11:50")]


def test_disabled_task_is_not_scheduled(tmp_path, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(T, "TASKS_FILE", tmp_path / "tasks.yml")
    monkeypatch.setattr(T, "_cache", {})
    monkeypatch.setattr(T, "_cache_mtime", None)

    T.save([replace(_brush(), enabled=False)])
    assert T.scheduled() == []
    assert T.spec("wash_hands").title == "饭前洗手"  # 仍可 --now 手动跑


def test_saved_yaml_omits_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "TASKS_FILE", tmp_path / "tasks.yml")
    monkeypatch.setattr(T, "_cache", {})
    monkeypatch.setattr(T, "_cache_mtime", None)

    T.save([TaskSpec(name="x", title="X")])
    text = (tmp_path / "tasks.yml").read_text(encoding="utf-8")
    assert "burst_frames" not in text, "跟默认值相同的字段不该写进文件"
    assert "name: x" in text
