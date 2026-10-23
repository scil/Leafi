"""对话大脑:Claude Haiku 生成教练台词(方案.md §5);无 API key 或调用失败时回退静态话术。

云端只收纯文字(任务名/环节/战绩数字),不含影像、不含身份信息 —— 方案.md §7 红线。
"""
import logging

from . import phrases
from .config import settings

log = logging.getLogger("brain")
_client = None

SYSTEM = (
    "你是一个 10 岁孩子的习惯教练,人设是『教练 + 队友』:平等、幽默、可以损一点,"
    "但只鼓励不训斥,忌幼稚化(不要叫小朋友、不要儿歌腔)。"
    "可用元素:连击(combo)、破纪录、战绩数字。"
    "输出恰好一句话、不超过 30 个字、口语化,将直接被 TTS 播放,不要用表情符号和引号。"
)


def _get_client():
    global _client
    if _client is None:
        import anthropic

        # TD-1: no SDK retries (a failure falls back to a static phrase at once), a bounded wait, no tracing
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0, timeout=10.0,
                                           open_telemetry=False)
    return _client


async def line(task: str, kind: str, context: str = "") -> str:
    """一句教练台词。task/kind 见 phrases.TASKS;context 例:'已连续打卡 5 天'。"""
    if not settings.anthropic_api_key:
        return phrases.pick(task, kind)
    try:
        msg = await _get_client().messages.create(
            model=settings.brain_model,
            max_tokens=100,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": f"场景:{phrases.title(task)};环节:{kind}。{context}\n给一句台词。",
            }],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return text or phrases.pick(task, kind)
    except Exception:
        log.warning("Claude 调用失败,回退静态话术", exc_info=True)
        return phrases.pick(task, kind)
