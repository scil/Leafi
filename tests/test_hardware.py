"""Real-model plumbing tests (plan S3 acceptance). Skipped unless LEAFI_HW_TESTS=1; they never play audio.

They prove plumbing, not tutoring accuracy; the child-speech evaluation (P-4) is separate.
"""

from __future__ import annotations

import pytest

from leafi.core.audio import read_wav
from leafi.core.config import Settings

pytestmark = pytest.mark.hardware


@pytest.fixture
def hw_settings(tmp_path):
    return Settings(_env_file=None, cache_dir=tmp_path / "cache")


async def test_kokoro_synthesises_a_wav(hw_settings):
    from leafi.services import tts

    service = tts.create(hw_settings, en="kokoro")
    clip = await service.synth("The little brown dog walked slowly.", "en")
    pcm, sr, _ = read_wav(clip.path)
    assert clip.duration_s > 1.0 and len(pcm) > sr


async def test_sherpa_transcribes_a_kokoro_sentence_and_alignment_commits_it(hw_settings):
    from leafi.services import asr, tts
    from leafi.study.alignment import ReadingState, align, complete_sentence

    text = "The little brown dog walked slowly."
    clip = await tts.create(hw_settings, en="kokoro").synth(text, "en")
    pcm, sr, _ = read_wav(clip.path)
    if sr != 16000:
        import numpy as np

        x = np.frombuffer(pcm, dtype="<i2").astype("float32")
        idx = np.linspace(0, len(x) - 1, int(len(x) * 16000 / sr))
        pcm = np.interp(idx, np.arange(len(x)), x).astype("<i2").tobytes()
    words = await asr.REGISTRY.create("sherpa", hw_settings).transcribe(pcm, 16000)
    st, _, events = align(ReadingState.from_text(text), [w.text for w in words], 1)
    st, cands = complete_sentence(st, 1)
    assert cands == [] and st.statuses() == "C C C C C C"
