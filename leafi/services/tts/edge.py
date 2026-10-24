"""edge-tts backend (Chinese by default), `library` mode of M5 design D14: each line is prepared by
`leafi.privacy.egress` first (pseudonymised, logged, attributed), then the `edge_tts` library runs unchanged under
a grant to its host for that one call and speaks exactly the prepared text. The TTS service never routes a
learner's own words or a line holding a protected name here while `PRIVACY_TTS_LEARNER_LINES` is `local`.

`edge_tts` is imported on first synthesis. Output is mp3 (24 kHz, 48 kbit/s); duration is estimated
from the file size because no decoder is required here.
"""

from __future__ import annotations

from pathlib import Path

from leafi.core.ports import SYSTEM, AudioClip, Provenance
from leafi.services._registry import has_package

_BITRATE = 48000
DESTINATION = "edge_tts"


class EdgeTts:
    name = "edge"
    model = "edge-24khz-48k"
    cloud = True

    def __init__(self, settings, lang: str = "zh", egress=None) -> None:
        self.settings = settings
        self.voice = settings.tts_voice_zh_edge if lang == "zh" else settings.tts_voice_en_edge
        self._egress = egress

    def egress(self):
        if self._egress is None:
            from leafi.privacy import runtime

            self._egress = runtime.get(self.settings)
        return self._egress

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path, *,
                         provenance: Provenance = SYSTEM) -> AudioClip:
        import edge_tts  # lazy

        from leafi.privacy.egress import Outgoing, Text

        path = out_base.with_suffix(".mp3")
        path.parent.mkdir(parents=True, exist_ok=True)
        e = self.egress()
        prepared = e.prepare(DESTINATION, "tts", Outgoing(json={"text": Text(text, provenance.cls,
                                                                            provenance.sources)}))
        spoken = prepared.json["text"]
        async with e.library_call(prepared):
            await edge_tts.Communicate(spoken, self.voice, rate="-25%" if slow else "+0%").save(str(path))
        dur = path.stat().st_size * 8 / _BITRATE
        return AudioClip(path, dur, 24000, 1, "mp3")


def create(settings, lang: str = "zh") -> EdgeTts:
    return EdgeTts(settings, lang)


def status(settings) -> tuple[str, str]:
    if not has_package("edge_tts"):
        return "missing package", "uv pip install --python .venv edge-tts"
    return "ok", "cloud: sends the spoken text, pseudonymised, to Microsoft"
