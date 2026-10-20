"""OpenPronounce backend (S3 shell, prototype P-4). Imported lazily; reference voice forced offline (Kokoro),
gTTS disabled, checkpoints pre-provisioned by `doctor` (ADR-0011). Inference must pass with LEAFI_NO_NETWORK=1.

The library's exact API is confirmed in P-4; until then `score()` raises NotImplementedError so nothing
can silently judge a child's pronunciation.
"""

from __future__ import annotations

from pathlib import Path

from leafi.core.ports import AudioRef
from leafi.services._registry import has_package
from leafi.services.pronunciation import PronScore


class OpenPronounceScorer:
    def __init__(self, settings) -> None:
        self.models_dir = Path(settings.models_dir) / "pronunciation"

    async def score(self, audio: AudioRef, expected: str) -> PronScore | None:
        import openpronounce  # noqa: F401  # lazy; API wiring is prototype P-4

        raise NotImplementedError("OpenPronounce wiring waits for prototype P-4 (PRON_AUTO_JUDGE stays off)")


def create(settings) -> OpenPronounceScorer:
    return OpenPronounceScorer(settings)


def status(settings) -> tuple[str, str]:
    if not has_package("openpronounce"):
        return "missing package", "uv pip install --python .venv openpronounce==0.3.0 (then prototype P-4)"
    if not (Path(settings.models_dir) / "pronunciation").exists():
        return "missing model", "provision wav2vec2 checkpoints into models/pronunciation (P-4)"
    return "ok", "auto judgement off unless PRON_AUTO_JUDGE=true"
