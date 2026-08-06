"""任务会话状态机(方案.md §6):提醒 → 等到场 → 验证 → 上报。

verify_mode=presence(P0):到场即记录;
verify_mode=vision(P1):刷牙走"姿态计分+门内停留+VLM 终裁",喝水走"抽帧 VLM 单判"。
"""
import asyncio
import base64
import logging

from . import brain, storage
from .config import settings
from .notify import send, snapshot
from .phrases import title
from .presence import presence
from .speaker import say

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
    if settings.verify_mode == "vision":
        if task.startswith("brush"):
            await _verify_brush(task, name)
            return
        if task == "water":
            await _verify_water(task, name)
            return
    storage.record(task, "present_late" if late else "present")
    suffix = "(第二次提醒后)" if late else ""
    await send(f"🟢 {name}:已到场{suffix}", "P0 仅确认到场,动作验证 P1 上线", with_snapshot=True)


async def _verify_brush(task: str, name: str) -> None:
    from .vision.dwell import InsideTracker
    from .vision.verifier import rtsp_kp_stream, run_brush_verification

    inside = InsideTracker()
    unsubscribe = presence.add_listener(inside.on_event)

    async def milestone(ms: int) -> None:
        await say(await brain.line(task, "milestone", f"已刷 {ms} 秒"))

    try:
        result = await run_brush_verification(
            rtsp_kp_stream(duration_s=settings.verify_window_s),
            inside,
            duration_s=settings.verify_window_s,
            fps_hint=8.0,
            on_milestone=milestone,
        )
    finally:
        unsubscribe()

    storage.record(
        task,
        "verified" if result.verified else "partial",
        active_seconds=result.brush_seconds,
        inside_seconds=result.inside_seconds,
        verified=result.verified,
        confidence=result.vlm.confidence if result.vlm else None,
    )
    await say(await brain.line(task, "done" if result.verified else "partial"))
    icon = "🟢" if result.verified else "🟡"
    await send(f"{icon} {name}:{result.summary()}", "", with_snapshot=True)


async def _verify_water(task: str, name: str) -> None:
    """喝水:动作短、无周期性 → 抽 8 帧交给本地 VLM 单判(水杯需在摄像头视野内)。"""
    from .vision.vlm import verdict

    frames: list[str] = []
    for _ in range(8):
        jpg = await snapshot()
        if jpg:
            frames.append(base64.b64encode(jpg).decode())
        await asyncio.sleep(4)
    v = await verdict(frames, kind="water")
    ok = bool(v and v.verified)
    storage.record(
        task,
        "verified" if ok else "partial",
        verified=ok,
        confidence=v.confidence if v else None,
    )
    await say(await brain.line(task, "done" if ok else "partial"))
    icon = "🟢" if ok else "🟡"
    detail = f"VLM 置信度 {v.confidence:.0%}" if v else "VLM 未启用,仅记录到场"
    await send(f"{icon} {name}:{'已确认喝水' if ok else '未确认到喝水动作'}", detail, with_snapshot=True)


def _streak_ctx() -> str:
    try:
        n = storage.streak_days()
        return f"当前连击 {n} 天" if n else ""
    except Exception:
        return ""
