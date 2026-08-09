"""任务会话状态机(方案.md §6):提醒 → 等到场 → 验证 → 上报。

验证策略不在这里写死,由 agent/tasks.py 的 TaskSpec.verify 决定;
verify_mode=presence(P0)时全局降级为"到场即记录"。
"""
import asyncio
import base64
import logging

from . import brain, storage
from .config import settings
from .notify import send, snapshot
from .presence import presence
from .speaker import say
from .tasks import TaskSpec, spec, title

log = logging.getLogger("session")


async def run_task(task: str) -> None:
    name = title(task)
    log.info("=== 任务开始:%s ===", name)
    await say(await brain.line(task, "opening", _streak_ctx()))

    if await presence.wait_for_person(settings.wait_presence_min * 60):
        await _arrived(task, name, late=False)
        return

    await say(await brain.line(task, "retry"))
    if await presence.wait_for_person(settings.wait_retry_min * 60):
        await _arrived(task, name, late=True)
        return

    storage.record(task, "missed")
    await send(f"⚠️ {name}:超时未到场", "两次提醒后仍未见到人,去人工催一下吧")


async def _arrived(task: str, name: str, late: bool) -> None:
    await say(await brain.line(task, "arrived"))
    ts = spec(task)
    if settings.verify_mode == "vision" and ts.verify in VERIFIERS:
        await VERIFIERS[ts.verify](ts, name)
        return
    storage.record(task, "present_late" if late else "present")
    suffix = "(第二次提醒后)" if late else ""
    await send(f"🟢 {name}:已到场{suffix}", "P0 仅确认到场,动作验证 P1 上线", with_snapshot=True)


async def _verify_pose_dwell(ts: TaskSpec, name: str) -> None:
    """周期性长动作:姿态计分 + 门内停留补分 + VLM 终裁。"""
    from .vision.dwell import InsideTracker
    from .vision.verifier import rtsp_kp_stream, run_pose_verification

    inside = InsideTracker()
    unsubscribe = presence.add_listener(inside.on_event)

    async def milestone(ms: int) -> None:
        await say(await brain.line(ts.name, "milestone", f"已做 {ms} 秒"))

    try:
        result = await run_pose_verification(
            rtsp_kp_stream(duration_s=settings.verify_window_s),
            inside,
            ts,
            duration_s=settings.verify_window_s,
            fps_hint=8.0,
            on_milestone=milestone,
        )
    finally:
        unsubscribe()

    storage.record(
        ts.name,
        "verified" if result.verified else "partial",
        active_seconds=result.active_seconds,
        inside_seconds=result.inside_seconds,
        verified=result.verified,
        confidence=result.vlm.confidence if result.vlm else None,
    )
    await say(await brain.line(ts.name, "done" if result.verified else "partial"))
    icon = "🟢" if result.verified else "🟡"
    await send(f"{icon} {name}:{result.summary()}", "", with_snapshot=True)


async def _verify_vlm_burst(ts: TaskSpec, name: str) -> None:
    """短促无周期的动作(喝水等):姿态计分对其无效,抽帧交本地 VLM 单判。"""
    from .vision.vlm import verdict

    frames: list[str] = []
    for _ in range(ts.burst_frames):
        jpg = await snapshot()
        if jpg:
            frames.append(base64.b64encode(jpg).decode())
        await asyncio.sleep(ts.burst_interval_s)
    v = await verdict(frames, kind=ts.vlm_kind or ts.name)
    ok = bool(v and v.verified)
    storage.record(
        ts.name,
        "verified" if ok else "partial",
        verified=ok,
        confidence=v.confidence if v else None,
    )
    await say(await brain.line(ts.name, "done" if ok else "partial"))
    icon = "🟢" if ok else "🟡"
    detail = f"VLM 置信度 {v.confidence:.0%}" if v else "VLM 未启用,仅记录到场"
    head = f"已确认{ts.title}" if ok else f"未确认到{ts.title}动作"
    await send(f"{icon} {name}:{head}", detail, with_snapshot=True)


VERIFIERS = {
    "pose_dwell": _verify_pose_dwell,
    "vlm_burst": _verify_vlm_burst,
}


def _streak_ctx() -> str:
    try:
        n = storage.streak_days()
        return f"当前连击 {n} 天" if n else ""
    except Exception:
        return ""
