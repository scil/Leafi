"""任务规格注册表:一个动作 = 一条 TaskSpec,验证策略由 spec 决定而非 if-else。

加新动作只需在 REGISTRY 里加一条 + 在 phrases.py 加一组话术
(vlm_burst 策略还需在 vision/vlm.py 的 PROMPTS 里加同名 key)。

两种验证策略的适用边界(方案.md §4):
  pose_dwell —— 动作有周期性且持续 ≥1 分钟(刷牙、洗手)。姿态计分 + 门内停留补分 + VLM 终裁。
  vlm_burst  —— 动作短促、无周期(喝水、吃药)。姿态计分器对它天然失效,只抽帧交 VLM 单判。
  presence   —— 不做动作验证,到场即记(P0 行为;verify_mode=presence 时全局回退到这条)。
"""
from dataclasses import dataclass, field

from .config import settings
from .vision.scorer import PRESETS


@dataclass(frozen=True)
class TaskSpec:
    name: str
    title: str
    verify: str                       # presence | pose_dwell | vlm_burst
    vlm_kind: str | None = None       # vision/vlm.py PROMPTS 的 key
    scorer: dict = field(default_factory=dict)   # MotionScorer 构造参数(anchor/axis/阈值)

    # --- pose_dwell 的达标线;None = 用 config 里的全局默认 ---
    target_seconds: int | None = None
    min_visible_seconds: int | None = None
    inside_credit_cap: int | None = None
    milestones: tuple[int, ...] = (30, 60, 90)

    # --- vlm_burst 的抽帧节奏 ---
    burst_frames: int = 8
    burst_interval_s: float = 4.0

    def resolved_target(self) -> int:
        return self.target_seconds or settings.target_active_seconds

    def resolved_min_visible(self) -> int:
        return self.min_visible_seconds or settings.min_visible_active_seconds

    def resolved_cap(self) -> int:
        cap = self.inside_credit_cap
        return settings.inside_credit_cap if cap is None else cap


REGISTRY: dict[str, TaskSpec] = {
    "water": TaskSpec(
        name="water",
        title="晨起喝水",
        verify="vlm_burst",
        vlm_kind="water",
    ),
    "brush_am": TaskSpec(
        name="brush_am",
        title="早刷牙",
        verify="pose_dwell",
        vlm_kind="brush",
        scorer=PRESETS["brush"],
    ),
    "brush_pm": TaskSpec(
        name="brush_pm",
        title="晚刷牙",
        verify="pose_dwell",
        vlm_kind="brush",
        scorer=PRESETS["brush"],
    ),
}


def spec(task: str) -> TaskSpec:
    """未注册的任务名回退为"仅到场",不让排错的 .env 直接把 agent 打崩。"""
    return REGISTRY.get(task) or TaskSpec(name=task, title=task, verify="presence")


def title(task: str) -> str:
    return spec(task).title
