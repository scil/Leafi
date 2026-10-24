"""Service registries, mocks, doctor, and the voice Listener composition (S3 shells)."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

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
    # every row says what it is for (+ sqlite, names, schools, wordlists)
    assert out.count("    for: ") == len(doctor.SERVICES) + 4
    assert set(doctor.PURPOSE) == {label for label, _, _ in doctor.SERVICES} | {"sqlite", "names", "schools", "wordlists"}
    assert "ANTHROPIC_API_KEY empty" in out
    assert "deferred" in out
    assert "REDACT_TERMS is empty" in out


def test_cli_devices_and_doctor_run(monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert cli.main(["doctor"]) == 0
    assert cli.main(["devices"]) == 0


class _EdgeRecorder:
    texts: list[str] = []

    def __init__(self, text, voice, rate="+0%"):
        _EdgeRecorder.texts.append(text)

    async def save(self, path):
        Path(path).write_bytes(b"\x00" * 600)


async def test_edge_backend_redacts_before_sending(settings, monkeypatch):
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _EdgeRecorder)
    _EdgeRecorder.texts = []
    settings.redact_terms = "Zephyrine,Quillfield Academy"
    service = tts.create(settings, en="edge", zh="edge")
    await service.synth("Good question! Let me think about \"Zephyrine\" at Quillfield Academy.", "en")
    assert _EdgeRecorder.texts and all("zephyrine" not in t.lower() and "quillfield" not in t.lower()
                                       for t in _EdgeRecorder.texts)


async def test_local_only_lines_never_reach_a_cloud_backend(settings, monkeypatch):
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _EdgeRecorder)
    _EdgeRecorder.texts = []
    mixed = tts.create(settings, en="edge", zh="mock")
    clip = await mixed.synth("Thanks! \"Zorblat\" it is.", "en", local_only=True)
    assert clip.codec == "wav" and _EdgeRecorder.texts == []  # spoken by the local backend
    cloud_only = tts.create(settings, en="edge", zh="edge")
    with pytest.raises(tts.LocalOnlyUnavailable):
        await cloud_only.synth("Thanks! \"Zorblat\" it is.", "en", local_only=True)
    assert _EdgeRecorder.texts == []


class QueueEar:
    """An async-generator Ear like LocalPcDevice.listen(): closing it on a timeout would end capture."""

    def __init__(self) -> None:
        self.q: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def listen(self):
        try:
            while True:
                yield AudioChunk(await self.q.get())
        finally:
            self.closed = True


async def test_a_listening_timeout_does_not_close_capture():
    """Review 1 #8."""
    ear = QueueEar()
    lis = asr.VoiceListener(ear, MockAsr(["the dog ran"]), pause_s=0.3)
    assert await lis.next_utterance(0.05) is None
    assert not ear.closed
    for pcm in [LOUD] * 3 + [QUIET] * 4:
        ear.q.put_nowait(pcm)
    u = await asyncio.wait_for(lis.next_utterance(2.0), 3)
    assert u is not None and u.text == "the dog ran"
