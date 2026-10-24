"""Voice mode plumbing: Silero segments in the VoiceListener, the sherpa result contract (P-1), capture loss
surfacing as LISTENER_LOST (TD-16) and a lost speech lease stopping the session (TD-15)."""

from __future__ import annotations

import asyncio

import pytest

from leafi.core.ports import AudioChunk, ListenerLost
from leafi.services import asr
from leafi.services.asr.mock import MockAsr
from leafi.services.asr.sherpa import words_from
from tests.test_services_mock import LOUD, QUIET, FakeEar

# ---------------------------------------------------------------- VoiceListener


class FakeVad:
    """Closes a segment every `every` chunks, whatever their energy."""

    def __init__(self, every: int = 3) -> None:
        self.every = every
        self.buf: list[bytes] = []
        self.resets = 0

    def feed(self, pcm: bytes, t: float | None = None) -> list[tuple[bytes, float | None]]:
        self.buf.append(pcm)
        if len(self.buf) >= self.every:
            seg, self.buf = b"".join(self.buf), []
            return [(seg, t)]
        return []

    def flush(self) -> list[tuple[bytes, float | None]]:
        seg, self.buf = b"".join(self.buf), []
        return [(seg, None)] if seg else []

    def reset(self) -> None:
        self.resets += 1
        self.buf = []


async def test_vad_segments_replace_the_energy_rule():
    ear = FakeEar([QUIET] * 10)  # silence throughout: the energy rule would never end-point
    lis = asr.VoiceListener(ear, MockAsr(["the dog ran"]), vad=FakeVad(every=3))
    u = await asyncio.wait_for(lis.next_utterance(5), 5)
    assert u.text == "the dog ran" and u.source == "voice" and len(u.audio_ref.pcm) == 3 * len(QUIET)


class SlowEar:
    """A few chunks, then nothing (asyncio.sleep below ~16 ms returns at once on Windows, so FakeEar floods)."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def listen(self):
        for pcm in self.chunks:
            await asyncio.sleep(0)
            yield AudioChunk(pcm)
        await asyncio.sleep(3600)
        yield AudioChunk(QUIET)


class SlowAsr(MockAsr):
    """Transcription slower than the READ window (`SENTENCE_PAUSE_S`), like Parakeet's first, model-loading call."""

    def __init__(self, texts: list[str], delay_s: float) -> None:
        super().__init__(texts)
        self.delay_s = delay_s

    async def transcribe(self, pcm, sample_rate, hotwords=None):
        await asyncio.sleep(self.delay_s)
        return await super().transcribe(pcm, sample_rate, hotwords)


async def test_a_read_cancelled_mid_transcription_keeps_its_speech():
    """Owner's voice runs (2026-10-21) lost the page's first lines: the session cancels a timed read when its
    window ends, and a segment still in the recognizer went with it. The next read must deliver it."""
    asr_ = SlowAsr(["the cat sat on the hat"], delay_s=0.3)
    lis = asr.VoiceListener(SlowEar([LOUD] * 3), asr_, vad=FakeVad(every=3))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(lis.next_utterance(0.1), 0.1)
    u = await asyncio.wait_for(lis.next_utterance(0.1), 1.0)
    assert u is not None and u.text == "the cat sat on the hat"
    assert asr_.calls == 1  # finished once, not transcribed again


async def test_pause_resets_the_vad_and_discards_buffered_audio():
    vad = FakeVad(every=50)
    lis = asr.VoiceListener(SlowEar([LOUD] * 5), MockAsr(["x"]), vad=vad)
    assert await lis.next_utterance(0.1) is None
    assert len(vad.buf) == 5  # fed, no segment yet
    await lis.pause()
    assert vad.resets >= 1 and vad.buf == []


class DyingEar:
    def __init__(self, chunks: list[bytes], error: BaseException | None) -> None:
        self.chunks = chunks
        self.error = error

    async def listen(self):
        for pcm in self.chunks:
            await asyncio.sleep(0)
            yield AudioChunk(pcm)
        if self.error is not None:
            raise self.error


async def test_capture_failure_surfaces_as_listener_lost_not_endless_none():
    """TD-16."""
    lis = asr.VoiceListener(DyingEar([QUIET], RuntimeError("PortAudio: device unavailable")), MockAsr())
    with pytest.raises(ListenerLost, match="device unavailable"):
        await asyncio.wait_for(lis.next_utterance(2), 5)
    with pytest.raises(ListenerLost):  # every later read says so too, instead of a quiet None
        await asyncio.wait_for(lis.next_utterance(0.1), 5)


async def test_an_ear_that_ends_is_listener_lost():
    lis = asr.VoiceListener(DyingEar([QUIET, QUIET], None), MockAsr())
    with pytest.raises(ListenerLost, match="capture ended"):
        await asyncio.wait_for(lis.next_utterance(2), 5)


# ---------------------------------------------------------------- sherpa contract (P-1)


def test_sherpa_words_from_space_prefixed_pieces_with_timing_and_confidence():
    tokens = [" The", " little", " br", "own", " do", "g", " w", "alk", "ed", " sl", "ow", "ly", "."]
    stamps = [0.0, 0.16, 0.4, 0.48, 0.64, 0.8, 0.96, 1.04, 1.2, 1.28, 1.44, 1.52, 1.68]
    durs = [0.16, 0.24, 0.08, 0.16, 0.16, 0.16, 0.08, 0.16, 0.08, 0.16, 0.08, 0.16, 0.16]
    lps = [0.0] * 13
    lps[2] = -0.5  # "br" of brown
    ws = words_from(tokens, stamps, durs, lps)
    assert [w.text for w in ws] == ["The", "little", "brown", "dog", "walked", "slowly."]
    assert ws[2].start_s == 0.4 and ws[2].end_s == pytest.approx(0.64) and 0.7 < ws[2].conf < 0.8
    assert ws[0].conf == 1.0 and ws[5].end_s == pytest.approx(1.84)
    assert words_from(["▁old", "▁style"], None, None, None) == [asr.Word("old"), asr.Word("style")]


def test_bpe_vocab_from_tokens_scores_longer_pieces_higher(tmp_path):
    from leafi.services.asr.sherpa import write_bpe_vocab

    tokens = tmp_path / "tokens.txt"
    tokens.write_text("<blk> 0\n▁t 1\n▁through 2\nough 3\n", encoding="utf-8")
    lines = write_bpe_vocab(tokens, tmp_path / "bpe.vocab").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("▁t\t") and "<blk>" not in "".join(lines)
    scores = {ln.split("\t")[0]: float(ln.split("\t")[1]) for ln in lines}
    assert scores["▁through"] > scores["ough"] > scores["▁t"]


# ---------------------------------------------------------------- session: LISTENER_LOST (TD-16)


# ---------------------------------------------------------------- session: lease lost (TD-15)


# ---------------------------------------------------------------- local_pc device resolution (P-6)


def test_local_pc_resolves_an_ambiguous_name_by_host_api_preference():
    from leafi.devices.local_pc import LocalPcDevice

    class FakeSd:
        apis = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]
        devices = [
            {"name": "Microphone (DJI Mic Mini)", "max_input_channels": 1, "hostapi": 0},
            {"name": "Microphone (DJI Mic Mini)", "max_input_channels": 1, "hostapi": 1},
            {"name": "Microphone (DJI Mic Mini)", "max_input_channels": 1, "hostapi": 2},
            {"name": "Speakers (DJI Mic Mini)", "max_input_channels": 0, "hostapi": 2},
        ]

        def query_devices(self):
            return self.devices

        def query_hostapis(self, i):
            return self.apis[i]

    assert LocalPcDevice(options={"input_device": "dji mic"})._resolve_device(FakeSd()) == 2
    assert LocalPcDevice(options={"input_device": "default"})._resolve_device(FakeSd()) is None
    assert LocalPcDevice(options={"input_device": "7"})._resolve_device(FakeSd()) == 7
    with pytest.raises(ListenerLost):
        LocalPcDevice(options={"input_device": "yeti"})._resolve_device(FakeSd())


class FakeSounddevice:
    """`sounddevice` stand-in whose stream calls back from a thread with fixed PCM every `block_s`."""

    def __init__(self, pcm_byte: bytes, name: str = "Voicemeeter Out A1 (VB-Audio Voicemeeter VAIO)"):
        self.pcm_byte = pcm_byte
        self.name = name
        fake = self

        class RawInputStream:
            device = 3
            active = True

            def __init__(self, *, samplerate, channels, dtype, device, blocksize, callback):
                self.blocksize, self.callback = blocksize, callback
                self._stop = None

            def __enter__(self):
                import threading

                self._stop = threading.Event()

                def run():
                    while not self._stop.wait(0.01):
                        self.callback(fake.pcm_byte * (2 * self.blocksize), self.blocksize, None, None)

                threading.Thread(target=run, daemon=True).start()
                return self

            def __exit__(self, *exc):
                self._stop.set()

        self.RawInputStream = RawInputStream

    def check_input_settings(self, **kw):
        return None

    def query_devices(self, device=None, kind=None):
        return {"name": self.name, "default_samplerate": 16000.0}


async def _drain(dev, seconds: float) -> int:
    n = 0
    async with asyncio.timeout(seconds):
        async for _ in dev.listen():
            n += 1
    return n


async def test_local_pc_treats_a_run_of_all_zero_blocks_as_a_lost_microphone(monkeypatch, caplog):
    """TD-26: the default input silently became a virtual device that delivers zeros."""
    import sys

    from leafi.devices.local_pc import LocalPcDevice

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSounddevice(b"\x00"))
    dev = LocalPcDevice(options={"block_s": 0.01, "zeros_lost_after_s": 0.2})
    caplog.set_level("INFO", logger="leafi.local_pc")
    with pytest.raises(ListenerLost, match="zeros"):
        await _drain(dev, 5)
    assert "Voicemeeter Out A1" in caplog.text  # the resolved default device is named at open


async def test_local_pc_keeps_capturing_a_quiet_but_live_microphone(monkeypatch):
    import sys

    from leafi.devices.local_pc import LocalPcDevice

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSounddevice(b"\x01"))
    dev = LocalPcDevice(options={"block_s": 0.01, "zeros_lost_after_s": 0.2})
    with pytest.raises(TimeoutError):
        await _drain(dev, 0.6)
