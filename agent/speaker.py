import logging

import httpx

from .config import settings
from .tts import synth

log = logging.getLogger("speaker")


async def say(text: str) -> None:
    path = await synth(text)
    if settings.mock:
        log.info("[MOCK 喇叭] %s  (%s)", text, path)
        return
    # 经 go2rtc 把音频推到摄像头喇叭(tapo:// 回传通道)。
    # cache/ 已挂载进 frigate 容器,go2rtc 按容器内路径 /cache/tts/... 读取。
    # src 具体语法待实机联调确认:https://github.com/AlexxIT/go2rtc#api
    src = f"ffmpeg:/cache/tts/{path.name}#audio=pcma"
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{settings.go2rtc_url}/api/streams",
                params={"dst": settings.stream_name, "src": src},
                timeout=10,
            )
            r.raise_for_status()
        log.info("喇叭播报: %s", text)
    except httpx.HTTPError:
        log.error("喇叭播报失败(go2rtc 不可达或 src 语法需调): %s", text, exc_info=True)
