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
    # 经 go2rtc 把音频推到摄像头喇叭(xiaomi://cs2 或 tapo:// 双向通道)。
    # 目标实例由 GO2RTC_URL 决定:小米机必须指宿主实例(:2984,P2P 连接的持有者),
    # SPEAKER_SRC_DIR 需与该实例的文件系统一致(宿主=Windows 路径,容器=/cache/tts)。
    src = f"ffmpeg:{settings.speaker_src_dir}/{path.name}#audio={settings.speaker_audio_codec}"
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
