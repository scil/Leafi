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


async def kokoro_pcm16(settings, text: str) -> bytes:
    """Kokoro's 24 kHz clip as 16 kHz mono int16 (what an Ear delivers)."""
    import numpy as np
    import soxr

    from leafi.services import tts

    clip = await tts.create(settings, en="kokoro").synth(text, "en")
    pcm, sr, _ = read_wav(clip.path)
    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    return soxr.resample(x, sr, 16000).astype("<i2").tobytes() if sr != 16000 else pcm


async def test_sherpa_transcribes_a_kokoro_sentence_and_alignment_commits_it(hw_settings):
    from leafi.services import asr
    from leafi.study.alignment import ReadingState, align, complete_sentence

    text = "The little brown dog walked slowly."
    pcm = await kokoro_pcm16(hw_settings, text)
    words = await asr.REGISTRY.create("sherpa", hw_settings).transcribe(pcm, 16000)
    assert [w.text.rstrip(".") for w in words] == ["The", "little", "brown", "dog", "walked", "slowly"]
    assert all(w.conf is not None and w.conf > 0.5 for w in words)  # P-1: ys_log_probs → per-word confidence
    assert words[0].start_s is not None and words[-1].end_s > words[0].start_s  # 80 ms token timing
    st, _, events = align(ReadingState.from_text(text), [w.text for w in words], 1)
    st, cands = complete_sentence(st, 1)
    assert cands == [] and st.statuses() == "C C C C C C"


async def test_rapidocr_reads_a_sideways_rendered_page(hw_settings):
    """P-3: the desk book lay at 270° to the camera. With the line classifier off and only wide lines counted
    (OCR design 2026-10-25 O2), the page is read upright at 270°, sure, by the probe or the scan."""
    import io

    from PIL import Image

    from leafi.core.ports import Frame
    from leafi.services import ocr
    from tests.fixtures.pages import PAGES, render

    img = Image.open(io.BytesIO(render(PAGES[0], number=1, width=1600).data)).rotate(90, expand=True)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    backend = ocr.REGISTRY.create("rapidocr", hw_settings)
    res = await backend.read(Frame(buf.getvalue()))
    await backend.aclose()
    assert res.good_lines >= 3 and res.rotation == 270 and res.state == "sure"
    assert "red kite" in res.text and res.confidence >= 0.9


@pytest.mark.parametrize("turn", [90, 180, 270])
async def test_rapidocr_reads_a_turned_page_upright_with_all_four_angles_listed(hw_settings, turn):
    import io

    from PIL import Image

    from leafi.core.ports import Frame
    from leafi.services import ocr
    from tests.fixtures.pages import PAGES, render

    img = Image.open(io.BytesIO(render(PAGES[1], width=1600).data)).rotate(turn, expand=True)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    backend = ocr.REGISTRY.create("rapidocr", hw_settings.model_copy(update={"ocr_rotations": "0,90,180,270"}))
    res = await backend.read(Frame(buf.getvalue()))
    await backend.aclose()
    assert res.rotation == (360 - turn) % 360 and res.state == "sure" and "found a shell" in res.text


async def test_sherpa_returns_nothing_for_short_silence_and_noise(hw_settings):
    """P-1: unpadded 0.1–0.4 s inputs hallucinated "Yeah." / "Mm-hmm."; the backend pads to 1 s."""
    import numpy as np

    from leafi.services import asr

    rec = asr.REGISTRY.create("sherpa", hw_settings)
    assert await rec.transcribe(b"\x00\x00" * 4800, 16000) == []
    noise = (np.random.default_rng(1).normal(0, 0.01, 4800) * 32767).astype("<i2").tobytes()
    assert await rec.transcribe(noise, 16000) == []


async def test_silero_vad_and_sherpa_segment_speech_through_the_voice_listener(hw_settings):
    """The S3 voice path minus the microphone: Ear chunks → Silero segment → Parakeet → aligned words."""
    import asyncio

    from leafi.core.ports import AudioChunk
    from leafi.services import asr
    from leafi.services.asr import vad as vad_module
    from leafi.study.alignment import ReadingState, align, complete_sentence

    text = "The little brown dog walked slowly."
    pcm = await kokoro_pcm16(hw_settings, text)
    step = 3200  # 100 ms

    class Ear:
        async def listen(self):
            for i in range(0, len(pcm), step):
                yield AudioChunk(pcm[i:i + step])
            for _ in range(15):  # 1.5 s of silence closes the segment (VAD_SILENCE_S 0.6)
                yield AudioChunk(b"\x00\x00" * 1600)
            await asyncio.sleep(3600)

    vad = vad_module.create(hw_settings, min_silence_s=0.6)
    listener = asr.VoiceListener(Ear(), asr.REGISTRY.create("sherpa", hw_settings), vad=vad)
    u = await asyncio.wait_for(listener.next_utterance(20), 60)
    assert u is not None and u.audio_ref is not None and len(u.audio_ref.pcm) >= len(pcm) * 0.8
    st, _, _ = align(ReadingState.from_text(text), [w.text for w in u.words], 1)
    st, cands = complete_sentence(st, 1)
    assert cands == [] and st.statuses() == "C C C C C C"
    await listener.close()


async def test_openpronounce_scores_offline_with_the_kokoro_reference(hw_settings, tmp_path):
    """P-4 plumbing: no network, bundled espeak, Leafi's Kokoro as the reference voice (ADR-0011)."""
    import os

    from leafi.core.ports import AudioRef
    from leafi.services import pronunciation

    learner = hw_settings.model_copy(update={"tts_voice_en_kokoro": "am_adam", "cache_dir": tmp_path / "learner"})
    scorer = pronunciation.REGISTRY.create("openpronounce", hw_settings)
    good = await scorer.score(AudioRef(await kokoro_pcm16(learner, "brown")), "brown")
    bad = await scorer.score(AudioRef(await kokoro_pcm16(learner, "banana")), "brown")
    assert good is not None and bad is not None and good.score >= 0.8 and bad.score <= 0.3
    assert good.phonemes_heard and os.environ.get("HF_HUB_OFFLINE") == "1" and os.environ.get("OPENPRONOUNCE_TTS") == "leafi"
