import logging
from urllib.parse import quote

import httpx

from .config import settings

log = logging.getLogger("notify")


async def snapshot() -> bytes | None:
    """取当前画面一帧(Frigate latest.jpg);失败返回 None。"""
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{settings.frigate_url}/api/{settings.camera_name}/latest.jpg", timeout=10
            )
            return r.content if r.status_code == 200 else None
    except httpx.HTTPError:
        log.warning("取快照失败")
        return None


async def send(title: str, body: str, with_snapshot: bool = False) -> None:
    log.info("[通知] %s — %s", title, body)
    if settings.mock:
        return
    # Images leave the LAN only when the owner opts in (NOTIFY_WITH_SNAPSHOT=true, ADR-0011).
    snap = await snapshot() if (with_snapshot and settings.notify_with_snapshot) else None
    try:
        async with httpx.AsyncClient() as c:
            if settings.bark_url:
                await c.get(
                    f"{settings.bark_url.rstrip('/')}/{quote(title)}/{quote(body or ' ')}",
                    timeout=10,
                )
            if settings.telegram_bot_token and settings.telegram_chat_id:
                api = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
                if snap:
                    await c.post(
                        f"{api}/sendPhoto",
                        data={"chat_id": settings.telegram_chat_id, "caption": f"{title}\n{body}"},
                        files={"photo": ("snapshot.jpg", snap, "image/jpeg")},
                        timeout=20,
                    )
                else:
                    await c.post(
                        f"{api}/sendMessage",
                        data={"chat_id": settings.telegram_chat_id, "text": f"{title}\n{body}"},
                        timeout=10,
                    )
    except httpx.HTTPError:
        log.error("通知发送失败", exc_info=True)
