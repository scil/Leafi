"""任务规格注册表:一个动作 = 一条 TaskSpec(标题/排程/验证策略/阈值/话术)。

数据源优先 `config/tasks.yml`——那是编辑界面(`python -m agent.webui`)读写的文件;
文件缺失时回退到本模块的 BUILTIN,保证裸克隆仓库也能跑。

读取带 mtime 检查:界面保存后**不必重启 agent**,下一次 spec() 就拿到新值。
例外是排程时刻——APScheduler 的 job 在启动时注册,改了要重启才生效。

加新动作的三步(REGISTRY→话术→PROMPTS)现在合成一步:界面里填完保存即可。
"""
from __future__ import annotations

import inspect
import logging
import os
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import yaml

from .config import settings
from .vision.scorer import PRESETS, MotionScorer
from .vision.vlm import PROMPTS

log = logging.getLogger("tasks")

TASKS_FILE = Path(__file__).resolve().parent.parent / "config" / "tasks.yml"

VERIFY_MODES = ("presence", "pose_dwell", "vlm_burst")
PHRASE_KINDS = ("opening", "retry", "arrived", "milestone", "done", "partial")
REQUIRED_PHRASES = ("opening", "retry", "arrived")
# 终裁提问里必须出现其中一句,否则等于放任模型去猜人是谁(红线 01)
GUARD_PHRASES = ("不要识别", "不得识别", "只判断动作")


def _has_guard(text: str) -> bool:
    return any(g in text for g in GUARD_PHRASES)


# 提问留空时可复用的内置 kind。自己也过一遍红线 01:vlm.py 里哪条提问漏了免责句,
# 它就不算"可复用",省得留空反而绕过校验。
BUILTIN_PROMPT_KINDS = tuple(k for k, v in PROMPTS.items() if _has_guard(v))
# MotionScorer 认识的构造参数(除 fps_hint,那个由 verifier 传)
SCORER_FIELDS = tuple(
    p for p in inspect.signature(MotionScorer).parameters if p != "fps_hint"
)


@dataclass(frozen=True)
class TaskSpec:
    name: str
    title: str
    verify: str = "presence"          # presence | pose_dwell | vlm_burst
    schedule: str = ""                # "HH:MM";留空 = 不排程(仍可 --now 手动跑)
    enabled: bool = True

    vlm_kind: str | None = None       # 终裁提问的 key
    prompt: str = ""                  # 提问正文;留空则用 vision/vlm.py 的内置 PROMPTS

    scorer: dict = field(default_factory=dict)          # MotionScorer 构造参数
    target_seconds: int | None = None
    min_visible_seconds: int | None = None
    inside_credit_cap: int | None = None
    milestones: tuple[int, ...] = (30, 60, 90)

    burst_frames: int = 8
    burst_interval_s: float = 4.0

    phrases: dict = field(default_factory=dict)         # kind -> [台词, ...]

    # ---- 阈值解析:None = 用 .env 的全局默认 ----
    def resolved_target(self) -> int:
        return self.target_seconds or settings.target_active_seconds

    def resolved_min_visible(self) -> int:
        return self.min_visible_seconds or settings.min_visible_active_seconds

    def resolved_cap(self) -> int:
        cap = self.inside_credit_cap
        return settings.inside_credit_cap if cap is None else cap

    def to_dict(self) -> dict:
        d = asdict(self)
        d["milestones"] = list(self.milestones)
        return d

    @staticmethod
    def from_dict(d: dict) -> TaskSpec:
        known = set(TaskSpec.__dataclass_fields__)
        clean = {k: v for k, v in d.items() if k in known}
        if "milestones" in clean:  # 缺这个键要留给 dataclass 的默认值,不能覆盖成空
            clean["milestones"] = tuple(clean["milestones"] or ())
        return TaskSpec(**clean)


BUILTIN: list[TaskSpec] = [
    TaskSpec(
        name="water",
        title="晨起喝水",
        verify="vlm_burst",
        schedule="07:20",
        vlm_kind="water",
    ),
    TaskSpec(
        name="brush_am",
        title="早刷牙",
        verify="pose_dwell",
        schedule="07:35",
        vlm_kind="brush",
        scorer=dict(PRESETS["brush"]),
    ),
    TaskSpec(
        name="brush_pm",
        title="晚刷牙",
        verify="pose_dwell",
        schedule="20:30",
        vlm_kind="brush",
        scorer=dict(PRESETS["brush"]),
    ),
]


# ---------------- 校验 ----------------

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate(spec: TaskSpec) -> list[str]:
    """返回人话错误列表;空列表 = 可保存。界面和单测共用这一份规则。"""
    errs: list[str] = []
    if not _NAME_RE.match(spec.name or ""):
        errs.append("名字只能用小写字母、数字、下划线,以字母开头(例:wash_hands)")
    if not (spec.title or "").strip():
        errs.append("标题不能为空(家长通知和话术里会用)")
    if spec.verify not in VERIFY_MODES:
        errs.append(f"验证策略只能是 {'/'.join(VERIFY_MODES)}")
    if spec.schedule and not _HHMM_RE.match(spec.schedule):
        errs.append("排程时刻要写成 HH:MM(留空 = 不排程)")

    for kind in REQUIRED_PHRASES:
        if not (spec.phrases.get(kind) or []):
            errs.append(f"话术「{kind}」至少要有一条")

    if spec.verify in ("pose_dwell", "vlm_burst"):
        kind = (spec.vlm_kind or "").strip()
        prompt = (spec.prompt or "").strip()
        if not kind:
            errs.append("要做终裁的动作必须填 vlm_kind")
        if prompt:
            # 红线 01:身份识别只在 Frigate 本地人脸做,不能让 VLM 去猜人是谁
            if not _has_guard(prompt):
                errs.append("终裁提问里必须写明「不要识别或猜测人物身份」(红线 01)")
        elif kind not in BUILTIN_PROMPT_KINDS:
            # 留空 = 复用 vlm.py 的内置提问,那些已含免责句;kind 不认识就只能自己写
            errs.append(
                "终裁提问不能为空(问模型「这是不是在做该动作」);"
                f"想留空复用内置提问,vlm_kind 得是 {'/'.join(BUILTIN_PROMPT_KINDS)} 之一"
            )

    if spec.verify == "pose_dwell":
        if not spec.scorer:
            errs.append("pose_dwell 必须给计分判据(anchor/axis 因动作而异,别吃默认值)")
        unknown = set(spec.scorer) - set(SCORER_FIELDS)
        if unknown:
            errs.append(f"计分判据里有 MotionScorer 不认识的参数:{', '.join(sorted(unknown))}")
        if spec.scorer.get("anchor") not in (None, "nose", "hip"):
            errs.append("anchor 只能是 nose 或 hip")
        if spec.scorer.get("axis") not in (None, "x", "y", "both"):
            errs.append("axis 只能是 x、y 或 both")
        if spec.resolved_min_visible() > spec.resolved_target():
            errs.append("最低可见秒数不能大于达标总秒数")
        if spec.resolved_cap() < 0:
            errs.append("门内停留上限不能是负数")
        if list(spec.milestones) != sorted(set(spec.milestones)):
            errs.append("里程碑要递增且不重复")
        if spec.milestones and spec.milestones[-1] > spec.resolved_target():
            errs.append("最后一个里程碑超过了达标秒数,永远播不出来")

    if spec.verify == "vlm_burst":
        if spec.burst_frames < 1:
            errs.append("连拍张数至少 1")
        if spec.burst_interval_s <= 0:
            errs.append("连拍间隔要大于 0 秒")

    return errs


def validate_all(specs: list[TaskSpec]) -> dict[str, list[str]]:
    """按任务名归组的错误表;另查重名。"""
    out: dict[str, list[str]] = {}
    seen: set[str] = set()
    for s in specs:
        errs = validate(s)
        if s.name in seen:
            errs.append("任务名重复")
        seen.add(s.name)
        if errs:
            out[s.name or "(未命名)"] = errs
    return out


# ---------------- 读写 ----------------

_cache: dict[str, TaskSpec] = {}
_cache_mtime: float | None = None
_from_file = False


def _read_file() -> list[TaskSpec] | None:
    try:
        raw = yaml.safe_load(TASKS_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError):
        log.warning("config/tasks.yml 读不出来,暂时用内置默认", exc_info=True)
        return None
    items = raw.get("tasks") or []
    specs = []
    for item in items:
        try:
            specs.append(TaskSpec.from_dict(item))
        except TypeError:
            log.warning("跳过写坏的任务条目:%r", item)
    return specs or None


def _load() -> None:
    global _cache, _cache_mtime, _from_file
    try:
        mtime = TASKS_FILE.stat().st_mtime
    except OSError:
        mtime = None
    if _cache and mtime == _cache_mtime:
        return
    specs = _read_file() if mtime is not None else None
    _from_file = specs is not None
    _cache = {s.name: s for s in (specs or BUILTIN)}
    _cache_mtime = mtime


def all_specs() -> list[TaskSpec]:
    _load()
    return list(_cache.values())


def spec(task: str) -> TaskSpec:
    """未注册的任务名回退为"仅到场",不让排错的配置直接把 agent 打崩。"""
    _load()
    return _cache.get(task) or TaskSpec(name=task, title=task, verify="presence")


def title(task: str) -> str:
    return spec(task).title


def exists(task: str) -> bool:
    _load()
    return task in _cache


def names() -> list[str]:
    _load()
    return list(_cache)


def scheduled() -> list[tuple[str, str]]:
    """排程表 [(任务名, "HH:MM")]。tasks.yml 存在时以它为准,否则回退 .env 的 SCHEDULE。"""
    _load()
    if _from_file:
        return [(s.name, s.schedule) for s in _cache.values() if s.enabled and s.schedule]
    return [(n, hhmm) for n, hhmm in settings.parsed_schedule() if n in _cache]


def _prune(spec: TaskSpec) -> dict:
    """写盘时省掉跟默认值相同的字段,YAML 干净、diff 只剩真正改过的东西。"""
    ref = TaskSpec(name=spec.name, title=spec.title).to_dict()
    return {
        k: v for k, v in spec.to_dict().items() if k in ("name", "title") or v != ref[k]
    }


def save(specs: list[TaskSpec]) -> None:
    """整表写回 config/tasks.yml(先写临时文件再替换,避免半截文件)。"""
    global _cache_mtime
    payload = {"version": 1, "tasks": [_prune(s) for s in specs]}
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TASKS_FILE.with_suffix(".yml.tmp")
    tmp.write_text(
        "# 由 python -m agent.webui 生成;手改也行,保存后 agent 会自动重读\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    os.replace(tmp, TASKS_FILE)
    _cache_mtime = None  # 强制下次重读
    _load()


def seed_defaults() -> None:
    """首次跑界面时,把内置默认(含话术与 PROMPTS)落成 tasks.yml。"""
    from .phrases import TASKS as STATIC_PHRASES
    from .vision.vlm import PROMPTS

    if TASKS_FILE.exists():
        return
    seeded = [
        replace(
            s,
            prompt=PROMPTS.get(s.vlm_kind or "", ""),
            phrases={k: list(v) for k, v in (STATIC_PHRASES.get(s.name) or {}).items()},
        )
        for s in BUILTIN
    ]
    save(seeded)
