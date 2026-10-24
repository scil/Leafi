"""`Utterance.ended_at` set by the devices (M7 design D21, rev 8): the end of the last voiced audio, not the chunk
that closed the segment; a typed line when Enter was pressed; speech cut by Leafi's own line never closes later."""

from __future__ import annotations

import asyncio
import io
import time
import wave
from pathlib import Path

import pytest

from leafi.core.ports import AudioChunk
from leafi.devices.console import ConsoleDevice
from leafi.services import asr
from leafi.services.asr.mock import MockAsr
from leafi.services.asr.vad import SileroVad
from tests.test_services_mock import LOUD, QUIET

ROOT = Path(__file__).resolve().parents[1]
SILERO = ROOT / "models" / "vad" / "silero_vad.onnx"
SPEECH = ROOT / "models" / "asr" / "parakeet-tdt-0.6b-v2-int8" / "test_wavs" / "0.wav"  # the model's own clip


class TimedEar:
    """Yields (pcm, t) chunks from a queue."""

    def __init__(self) -> None:
        self.q: asyncio.Queue = asyncio.Queue()

    async def listen(self):
        while True:
            pcm, t = await self.q.get()
            yield AudioChunk(pcm, t=t)


async def test_the_energy_segmenter_stamps_the_last_loud_chunk():
    ear = TimedEar()
    for i, pcm in enumerate([QUIET, LOUD, LOUD, LOUD] + [QUIET] * 13):
        ear.q.put_nowait((pcm, 100.0 + i / 10))
    u = await asyncio.wait_for(asr.VoiceListener(ear, MockAsr(["the dog ran"]), pause_s=1.2).next_utterance(5), 5)
    assert u.ended_at == pytest.approx(100.3)  # the third loud chunk, not the closing silence 1.2 s later


async def test_speech_cut_by_leafis_line_never_closes_after_the_resume():
    ear = TimedEar()
    lis = asr.VoiceListener(ear, MockAsr(["half a sentence"]), pause_s=0.3)
    read = asyncio.create_task(lis.next_utterance(0.8))
    for _ in range(3):
        ear.q.put_nowait((LOUD, time.monotonic()))
    await asyncio.sleep(0.1)  # the segmenter holds the speech
    await lis.pause()  # Leafi speaks
    await lis.resume()
    for _ in range(5):
        ear.q.put_nowait((QUIET, time.monotonic()))
    assert await asyncio.wait_for(read, 3) is None  # not delivered as an answer to the next question


def test_the_vad_maps_a_segments_last_sample_onto_the_chunks_time():
    vad = SileroVad.__new__(SileroVad)  # the mapping only; the detector itself is measured below
    vad.sample_rate, vad._marks = 16000, [(1600, 10.0), (3200, 10.1)]
    assert vad.end_t(2400) == pytest.approx(10.05)
    assert vad.end_t(1600) == pytest.approx(10.0)
    assert vad.end_t(5000) is None


@pytest.mark.skipif(not (SILERO.exists() and SPEECH.exists()), reason="Silero and the Parakeet test clip")
def test_silero_end_t_is_the_end_of_speech_also_after_a_reset():
    """Measured 2026-10-24 on sherpa-onnx 1.13.8: `seg.start` restarts at 0 after `reset()`."""
    pytest.importorskip("sherpa_onnx")
    with wave.open(str(SPEECH)) as f:
        speech = f.readframes(f.getnframes())
    silence = b"\x00\x00" * 32000  # 2 s
    vad = SileroVad(SILERO)
    for base in (0.0, 100.0):
        data, chunk, fed, ends = silence + speech + silence, 1024, 0, []
        for i in range(0, len(data), chunk):
            fed += len(data[i:i + chunk]) // 2
            ends += [e for _, e in vad.feed(data[i:i + chunk], base + fed / 16000)]
        speech_end = base + 2 + len(speech) / 32000
        assert ends and speech_end - 0.5 < ends[-1] <= speech_end + 0.05
        vad.reset()


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


async def test_a_typed_line_is_stamped_when_enter_was_pressed():
    dev = ConsoleDevice(stdin=Terminal("hello\n"), stdout=io.StringIO())
    dev._ensure_reader()
    await asyncio.sleep(0.2)  # typed before anyone listened
    asked = time.monotonic()
    u = await dev.next_utterance(1)
    assert u.text == "hello" and u.ended_at is not None and u.ended_at < asked


async def test_piped_lines_are_not_stamped_at_read_ahead():
    """Piped stdin is read all at once: stamping it would date every scripted line to the session's start, so a
    script's answers would belong to the first prompt (found by `test_privacy`'s piped session, 2026-10-24)."""
    dev = ConsoleDevice(stdin=io.StringIO("one\ntwo\n"), stdout=io.StringIO())
    assert (await dev.next_utterance(1)).ended_at is None
    assert (await dev.next_utterance(1)).ended_at is None
