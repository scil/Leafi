import hashlib
from pathlib import Path

import edge_tts

from .config import settings

CACHE = Path("cache/tts")


async def synth(text: str) -> Path:
    """Edge-TTS 合成并缓存;返回本地文件路径(容器内对应 /cache/tts/<name>)。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{settings.tts_voice}|{text}".encode()).hexdigest()
    out = CACHE / f"{key}.mp3"
    if not out.exists():
        await edge_tts.Communicate(text, settings.tts_voice).save(str(out))
    return out
