"""Service registries, mocks, doctor, and the voice Listener composition (S3 shells)."""

from __future__ import annotations

import asyncio
import io
import sys

import pytest

from leafi import doctor
from leafi.core.ports import AudioChunk
from leafi.services import asr, brain, ocr, pronunciation, tts
from leafi.services.asr.mock import MockAsr

LOUD = (b"\x00\x20" * 1600)  # 0.1 s of int16 at amplitude 8192
QUIET = b"\x00\x00" * 1600


class FakeEar:
    def __init__(self, pattern: list[bytes]) -> None:
        self.pattern = pattern

    async def listen(self):
        for pcm in self.pattern:
            await asyncio.sleep(0)
            yield AudioChunk(pcm)
        while True:
            await asyncio.sleep(0.01)
            yield AudioChunk(QUIET)


async def test_voice_listener_endpoints_speech_and_attaches_audio():
    ear = FakeEar([QUIET, LOUD, LOUD, LOUD] + [QUIET] * 13)
    lis = asr.VoiceListener(ear, MockAsr(["the dog ran"]), pause_s=1.2)
    u = await asyncio.wait_for(lis.next_utterance(5), 5)
    assert u.text == "the dog ran" and not u.typed and u.audio_ref is not None
    assert len(u.audio_ref.pcm) >= 3 * len(LOUD)


async def test_voice_listener_discards_audio_while_paused_and_times_out():
    t = [0.0]
    lis = asr.VoiceListener(FakeEar([LOUD] * 5), MockAsr(["leafi talking"]), clock=lambda: t[0])
    await lis.pause()
    assert await lis.next_utterance(0.2) is None
    await lis.resume(after_s=0.6)
    assert not lis._gate_open()
    t[0] = 1.0
    assert lis._gate_open()


async def test_sherpa_hotwords_are_not_implemented_until_p1(settings):
    rec = asr.REGISTRY.create("sherpa", settings)
    with pytest.raises(NotImplementedError):
        await rec.transcribe(b"", 16000, hotwords=["through"])


async def test_tts_mock_is_cached_by_text_lang_voice_speed_model(settings):
    service = tts.create(settings)
    a = await service.synth("Let's try that word.", "en")
    b = await service.synth("Let's try that word.", "en")
    c = await service.synth("Let's try that word.", "en", slow=True)
    assert a.path == b.path and a.path != c.path
    assert c.duration_s > a.duration_s
    assert service.backends["en"].calls == [("Let's try that word.", "en", False), ("Let's try that word.", "en", True)]


def test_registries_know_mock_backends_and_deferred_ones(settings):
    for reg in (asr.REGISTRY, tts.REGISTRY, ocr.REGISTRY, pronunciation.REGISTRY, brain.REGISTRY):
        assert "mock" in reg.backends
    assert ocr.REGISTRY.status("qwen_vl", settings)[0] == "deferred"
    with pytest.raises(LookupError):
        ocr.REGISTRY.create("qwen_vl", settings)


def test_doctor_reports_every_service(settings):
    settings.asr_backend, settings.tts_backend_en, settings.ocr_backend = "sherpa", "kokoro", "rapidocr"
    settings.brain_backend = "claude"
    out = doctor.report(settings)
    for label in ("asr", "tts en", "tts zh", "ocr", "pronunciation", "brain", "book lookup"):
        assert label in out
    assert "ANTHROPIC_API_KEY empty" in out
    assert "deferred" in out
    assert "REDACT_TERMS is empty" in out


def test_cli_devices_and_doctor_run(monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert cli.main(["doctor"]) == 0
    assert cli.main(["devices"]) == 0
