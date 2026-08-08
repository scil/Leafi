import asyncio
import hashlib
from pathlib import Path

import edge_tts

from .config import settings

CACHE = Path("cache/tts")

# 首尾垫静音(毫秒/秒):头部防摄像头喇叭功放唤醒吃字,尾部防拆流截尾。
PAD_HEAD_MS = 900
PAD_TAIL_S = 0.6


async def synth(text: str) -> Path:
    """Edge-TTS 合成 + 首尾垫静音,缓存;返回本地文件路径。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{settings.tts_voice}|{text}".encode()).hexdigest()
    out = CACHE / f"{key}.mp3"
    if out.exists():
        return out

    raw = CACHE / f"{key}.raw.mp3"
    await edge_tts.Communicate(text, settings.tts_voice).save(str(raw))
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "quiet", "-i", str(raw),
        "-af", f"adelay={PAD_HEAD_MS}:all=1,apad=pad_dur={PAD_TAIL_S}", str(out),
    )
    await proc.wait()
    if proc.returncode == 0 and out.exists():
        raw.unlink(missing_ok=True)
    else:
        raw.rename(out)  # 无 ffmpeg 时退化为原始音频
    return out
