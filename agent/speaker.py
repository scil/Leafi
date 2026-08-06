import asyncio
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
    if settings.speaker_backend == "local":
        await _play_local(path)
        log.info("本机播报: %s", text)
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


async def _play_local(path) -> None:
    """开发用:ffplay 在 PC 上直接播放(已确认本机装有 ffmpeg 全家桶)。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)
        )
        await proc.wait()
    except FileNotFoundError:
        log.error("找不到 ffplay;请安装 ffmpeg 或把 SPEAKER_BACKEND 改回 go2rtc")
