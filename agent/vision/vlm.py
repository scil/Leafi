"""本地 VLM 终裁(方案.md §4 L3):Ollama + Qwen3-VL,影像零出网。

prompt 只问动作、不问身份 —— 身份识别只在 Frigate 本地人脸做(方案.md §7 红线)。
"""
import json
import logging
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger("vlm")

PROMPTS = {
    "brush": (
        "这些是家用走廊摄像头在一次刷牙任务期间抽取的画面。"
        "判断画面中的孩子是否在刷牙(手持牙刷或牙刷在口中、有刷牙动作)。"
        "只判断动作,不要识别或猜测人物身份。按 JSON 输出。"
    ),
    "water": (
        "这些是家用走廊摄像头在晨起喝水任务期间抽取的画面。"
        "判断画面中的孩子是否在喝水(手持水杯、仰头饮水)。"
        "只判断动作,不要识别或猜测人物身份。按 JSON 输出。"
    ),
}

SCHEMA = {
    "type": "object",
    "properties": {
        "verified": {"type": "boolean"},
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["verified", "confidence"],
}


@dataclass
class Verdict:
    verified: bool
    confidence: float
    note: str = ""


def parse_verdict(content: str) -> Verdict:
    data = json.loads(content)
    return Verdict(
        verified=bool(data["verified"]),
        confidence=float(data.get("confidence", 0.0)),
        note=str(data.get("note", "")),
    )


async def verdict(images_b64: list[str], kind: str = "brush") -> Verdict | None:
    """返回 None = 终裁不可用(Ollama 未起/模型未拉),调用方以 L2 计分为准。"""
    if not images_b64:
        return None
    payload = {
        "model": settings.vlm_model,
        "stream": False,
        "messages": [{"role": "user", "content": PROMPTS[kind], "images": images_b64}],
        "format": SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{settings.ollama_url}/api/chat", json=payload, timeout=180)
            r.raise_for_status()
            return parse_verdict(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError):
        log.warning("VLM 终裁不可用,以姿态计分为准", exc_info=True)
        return None
