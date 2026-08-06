import logging

from . import phrases, storage
from .config import settings
from .notify import send
from .presence import presence
from .speaker import say

log = logging.getLogger("session")


async def run_task(task: str) -> None:
    """P0 流程:提醒 → 等到场 → (二次提醒) → 推送结果。P1 在'到场'后接视觉验证。"""
    name = phrases.title(task)
    log.info("=== 任务开始:%s ===", name)
    await say(phrases.pick(task, "opening"))

    if await presence.wait_for_person(settings.wait_presence_min * 60):
        await _arrived(task, name, late=False)
        return

    await say(phrases.pick(task, "retry"))
    if await presence.wait_for_person(settings.wait_retry_min * 60):
        await _arrived(task, name, late=True)
        return

    storage.save(task, "missed")
    await send(f"⚠️ {name}:超时未到场", "两次提醒后仍未见到人,去人工催一下吧")


async def _arrived(task: str, name: str, late: bool) -> None:
    await say(phrases.pick(task, "arrived"))
    storage.save(task, "present_late" if late else "present")
    suffix = "(第二次提醒后)" if late else ""
    await send(f"🟢 {name}:已到场{suffix}", "P0 仅确认到场,动作验证 P1 上线", with_snapshot=True)
