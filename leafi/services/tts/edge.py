"""edge-tts backend (Chinese by default). Egress: Leafi-authored lines only, after REDACT_TERMS redaction; the
TTS service never routes a local-only line (learner-originated text) here (security.md egress table).

`edge_tts` is imported on first synthesis. Output is mp3 (24 kHz, 48 kbit/s); duration is estimated
from the file size because no decoder is required here.
"""

from __future__ import annotations

from pathlib import Path

from leafi.core.ports import AudioClip
from leafi.core.text import redact
from leafi.services._registry import has_package

_BITRATE = 48000


class EdgeTts:
    name = "edge"
    model = "edge-24khz-48k"
    cloud = True

    def __init__(self, settings, lang: str = "zh") -> None:
        self.redact_terms = settings.redact_list()
        self.voice = settings.tts_voice_zh_edge if lang == "zh" else settings.tts_voice_en_edge

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path) -> AudioClip:
        import edge_tts  # lazy

        path = out_base.with_suffix(".mp3")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = redact(text, self.redact_terms)  # Leafi-authored lines only, redacted (security.md)
        await edge_tts.Communicate(text, self.voice, rate="-25%" if slow else "+0%").save(str(path))
        dur = path.stat().st_size * 8 / _BITRATE
        return AudioClip(path, dur, 24000, 1, "mp3")


def create(settings, lang: str = "zh") -> EdgeTts:
    return EdgeTts(settings, lang)


def status(settings) -> tuple[str, str]:
    if not has_package("edge_tts"):
        return "missing package", "uv pip install --python .venv edge-tts"
    return "ok", "cloud: sends the spoken text to Microsoft"
