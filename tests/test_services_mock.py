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


@pytest.fixture
def edge_egress(settings, monkeypatch):
    """edge-tts through a real Egress whose edge destination is loopback (nothing resolves or leaves); the
    library itself is replaced by a recorder."""
    import edge_tts

    from leafi.core import learner_store
    from leafi.core.storage import Store
    from leafi.privacy import destinations as dests
    from leafi.privacy import egress as eg
    from leafi.privacy import runtime, secret

    monkeypatch.setattr(edge_tts, "Communicate", _EdgeRecorder)
    _EdgeRecorder.texts = []
    secret._forget_cache()
    store = Store(settings.db_path)
    lid = learner_store.create(store, "Zephyrine")
    store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('Quillfield Academy', 'school', 't')")
    reg = dests.registry(settings)
    reg["edge_tts"] = dests.Destination("edge_tts", "wss", frozenset({"127.0.0.1"}), 9, frozenset({"tts"}), "cloud")
    e = eg.Egress(settings, registry=reg, env_file=None)
    runtime.use(e)
    with runtime.attributed(lid):
        yield type("E", (), {"store": store, "learner": lid, "egress": e})
    runtime.use(None)
    store.close()


async def test_a_line_with_a_protected_name_never_reaches_edge(settings, edge_egress):
    cloud_only = tts.create(settings, en="edge", zh="edge")
    with pytest.raises(tts.LocalOnlyUnavailable):  # stays local; no local backend → shown on Faces only
        await cloud_only.synth("Good question, Zephyrine! Let me think about Quillfield Academy.", "en")
    assert _EdgeRecorder.texts == []
    clip = await cloud_only.synth("Good question! Let me think.", "en")
    assert clip.codec == "mp3" and _EdgeRecorder.texts == ["Good question! Let me think."]
    rows = edge_egress.store.all("SELECT destination, purpose, learner_id, status FROM egress_log")
    assert [tuple(r) for r in rows] == [("edge_tts", "tts", edge_egress.learner, "sent")]


async def test_with_cloud_learner_lines_edge_speaks_only_surrogates(settings, edge_egress):
    service = tts.create(settings, en="edge", zh="edge")
    service.learner_lines = "cloud"  # PRIVACY_TTS_LEARNER_LINES=cloud: ADR-0018 lets edge speak surrogates
    await service.synth("Good question, Zephyrine! Let me think about Quillfield Academy.", "en")
    (said,) = _EdgeRecorder.texts
    assert "Zephyrine" not in said and "Quillfield" not in said and "the school" in said


async def test_a_learners_own_words_never_reach_a_cloud_backend(settings, edge_egress):
    from leafi.core.ports import Provenance

    mine = Provenance("learner", (edge_egress.learner,))
    mixed = tts.create(settings, en="edge", zh="mock")
    clip = await mixed.synth("Thanks! \"Zorblat\" it is.", "en", provenance=mine)
    assert clip.codec == "wav" and _EdgeRecorder.texts == []  # spoken by the local backend
    cloud_only = tts.create(settings, en="edge", zh="edge")
    with pytest.raises(tts.LocalOnlyUnavailable):
        await cloud_only.synth("Thanks! \"Zorblat\" it is.", "en", provenance=mine)
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
