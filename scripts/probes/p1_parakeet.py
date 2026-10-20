"""Prototype P-1: the exact Python result contract of sherpa-onnx with the Parakeet TDT 0.6B v2 int8 export.

Questions (plan → Prototypes): token→word reconstruction, timing granularity, whether a confidence exists,
behaviour on silence, whether hotwords apply with `modified_beam_search` for `model_type="nemo_transducer"`,
and CPU latency against the 0.6 s budget (performance.md). Throwaway: prints a report, writes nothing.

Run:  .venv\\Scripts\\python scripts/probes/p1_parakeet.py   (needs models/asr/… and models/tts/… from `doctor`)
Audio comes from Kokoro (local) and the tarball's test wav; nothing is played anywhere.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leafi.core.config import Settings  # noqa: E402

MODEL = ROOT / "models/asr/parakeet-tdt-0.6b-v2-int8"
SENTENCES = [
    "The little brown dog walked slowly.",
    "I can see a big red ball under the old wooden table today.",  # 12 words: latency probe
    "The quokka and the pterodactyl met Leafi at the lighthouse.",  # rare words: hotword probe
]


def to_16k(pcm: bytes, sr: int) -> np.ndarray:
    x = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
    if sr == 16000:
        return x
    import soxr

    return soxr.resample(x, sr, 16000).astype("float32")


def recognizer(decoding: str = "greedy_search", hotwords_file: str = "", modeling_unit: str = "cjkchar",
               bpe_vocab: str = "", threads: int = 2, hotwords_score: float = 1.5):
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(MODEL / "encoder.int8.onnx"), decoder=str(MODEL / "decoder.int8.onnx"),
        joiner=str(MODEL / "joiner.int8.onnx"), tokens=str(MODEL / "tokens.txt"), model_type="nemo_transducer",
        num_threads=threads, decoding_method=decoding, hotwords_file=hotwords_file, hotwords_score=hotwords_score,
        modeling_unit=modeling_unit, bpe_vocab=bpe_vocab)


def decode(rec, samples: np.ndarray):
    s = rec.create_stream()
    s.accept_waveform(16000, samples)
    t0 = time.perf_counter()
    rec.decode_stream(s)
    return s.result, time.perf_counter() - t0


def words_from(res) -> list[tuple[str, float | None, float | None]]:
    """Token→word rule used by leafi/services/asr/sherpa.py: a token starting with ▁ opens a word."""
    out: list[list] = []
    stamps = list(res.timestamps or [])
    durs = list(getattr(res, "durations", None) or [])
    for k, tok in enumerate(res.tokens):
        t = stamps[k] if k < len(stamps) else None
        d = durs[k] if k < len(durs) else None
        end = (t + d) if (t is not None and d is not None) else t
        if tok.startswith("▁") or not out:
            out.append([tok.lstrip("▁"), t, end])
        else:
            out[-1][0] += tok
            out[-1][2] = end
    return [(w, a, b) for w, a, b in out if w]


async def kokoro_clips(sentences: list[str]) -> dict[str, np.ndarray]:
    from leafi.core.audio import read_wav
    from leafi.services import tts

    settings = Settings(_env_file=None, cache_dir=Path(tempfile.mkdtemp(prefix="p1-")))
    service = tts.create(settings, en="kokoro", zh="kokoro")
    out = {}
    for s in sentences:
        clip = await service.synth(s, "en")
        pcm, sr, _ = read_wav(clip.path)
        out[s] = to_16k(pcm, sr)
    return out


def wav_file(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return to_16k(w.readframes(w.getnframes()), w.getframerate())


def synth_bpe_vocab(tokens_txt: Path) -> Path:
    """A `bpe.vocab` for ssentencepiece built from tokens.txt (piece<TAB>score); the real sentencepiece model is
    not in the tarball. Longer pieces get a higher score so encoding prefers whole-word pieces."""
    lines = []
    for line in tokens_txt.read_text(encoding="utf-8").splitlines():
        piece, _, _ = line.rpartition(" ")
        if piece in ("<unk>", "<blk>", "<s>", "</s>") or not piece:
            continue
        lines.append(f"{piece}\t{-1.0 / len(piece):.4f}")
    p = Path(tempfile.gettempdir()) / "p1-bpe.vocab"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def main() -> None:
    import sherpa_onnx

    print(f"sherpa-onnx {sherpa_onnx.__version__}; model {MODEL.name}")
    rec = recognizer()
    test_wav = MODEL / "test_wavs" / "0.wav"
    res, dt = decode(rec, wav_file(test_wav))
    print("\n## Result object")
    print("attributes:", [a for a in dir(res) if not a.startswith("_")])
    print("text:", repr(res.text))
    print("tokens[:12]:", res.tokens[:12])
    print("timestamps[:12]:", [round(t, 2) for t in list(res.timestamps)[:12]])
    for name in ("durations", "ys_probs", "lm_probs", "context_scores", "words", "lang", "emotion", "event"):
        if hasattr(res, name):
            v = getattr(res, name)
            v = list(v)[:12] if hasattr(v, "__iter__") and not isinstance(v, str) else v
            print(f"{name}:", v)
    print("words (▁ rule):", words_from(res)[:8])
    print(f"decode {dt:.3f}s for {test_wav.name}")

    print("\n## Silence and noise")
    for label, x in (("2 s digital silence", np.zeros(32000, dtype="float32")),
                     ("2 s low noise (rms 0.003)", (np.random.default_rng(0).normal(0, 0.003, 32000)).astype("float32")),
                     ("0.3 s silence", np.zeros(4800, dtype="float32"))):
        r, dt = decode(rec, x)
        print(f"{label}: text={r.text!r} tokens={list(r.tokens)} ({dt:.3f}s)")

    clips = asyncio.run(kokoro_clips(SENTENCES))
    print("\n## Kokoro sentences, greedy_search, 2 threads")
    for s, x in clips.items():
        r, dt = decode(rec, x)
        ws = words_from(r)
        print(f"- expected: {s}\n  heard:    {r.text!r}  ({dt:.3f}s for {len(x)/16000:.2f}s audio)")
        print("  words:", [(w, None if a is None else round(a, 2), None if b is None else round(b, 2)) for w, a, b in ws])

    print("\n## Latency (12-word sentence), CPU")
    x = clips[SENTENCES[1]]
    for threads in (2, 4, 8):
        r = recognizer(threads=threads)
        decode(r, x)  # warm
        times = [decode(r, x)[1] for _ in range(3)]
        print(f"threads={threads}: {['%.3f' % t for t in times]} s")

    print("\n## modified_beam_search")
    try:
        rb = recognizer("modified_beam_search")
        for s, x in clips.items():
            r, dt = decode(rb, x)
            print(f"- {r.text!r} ({dt:.3f}s)")
    except Exception as e:  # noqa: BLE001
        print("modified_beam_search failed:", type(e).__name__, e)

    print("\n## Hotwords (modified_beam_search)")
    hot = Path(tempfile.gettempdir()) / "p1-hotwords.txt"
    hot.write_text("quokka\npterodactyl\nLeafi\n", encoding="utf-8")
    x = clips[SENTENCES[2]]
    for unit, vocab in (("cjkchar", ""), ("bpe", str(synth_bpe_vocab(MODEL / "tokens.txt")))):
        for score in (1.5, 3.0):
            try:
                rh = recognizer("modified_beam_search", str(hot), unit, vocab, hotwords_score=score)
                r, dt = decode(rh, x)
                print(f"- unit={unit} score={score}: {r.text!r} ({dt:.3f}s)")
            except Exception as e:  # noqa: BLE001
                print(f"- unit={unit} score={score}: failed: {type(e).__name__}: {str(e)[:200]}")

    print("\n## JSON of one result (for the contract)")
    r, _ = decode(rec, clips[SENTENCES[0]])
    print(json.dumps({"text": r.text, "tokens": list(r.tokens), "timestamps": [round(t, 3) for t in r.timestamps],
                      "durations": [round(d, 3) for d in getattr(r, "durations", [])]}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
