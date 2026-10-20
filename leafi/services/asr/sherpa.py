"""sherpa-onnx offline transducer (Parakeet TDT 0.6B v2 int8). Imported lazily.

Result contract measured by prototype P-1 (2026-10-20, sherpa-onnx 1.13.8; plan → Surprises):
- `result.tokens` are sentencepiece pieces whose word-initial pieces start with a **space** (`" The"`), not `▁`;
  punctuation is its own piece (`","`, `"."`) and is glued to the previous word, `norm()` strips it later.
- `result.timestamps` and `result.durations` are per token at 80 ms frame granularity; `words` is empty.
- `result.ys_log_probs` is one log-probability per token, so a per-word confidence exists: exp(mean).
- ≥ 0.5 s of silence or noise decodes to nothing; inputs shorter than that hallucinate (`"Yeah."`, `"Mm-hmm."`
  with a first-token log-prob below −1), so every segment is padded with silence to `MIN_SECONDS`.
- `modified_beam_search` works for `model_type="nemo_transducer"`; hotwords apply only with
  `modeling_unit="bpe"` and a `bpe.vocab`, which the tarball lacks: a vocab built from `tokens.txt` works and
  is written next to the model on first use. Hotwords are per stream (`create_stream(hotwords)`), so one
  recognizer serves biased and unbiased calls; `ASR_HOTWORDS=off` keeps them unused (ADR-0011).
- CPU latency for a 12-word sentence: 0.17 s at 2 threads, 0.09 s at 8 (budget 0.6 s, performance.md).
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

from leafi.core.ports import Word
from leafi.services._registry import has_package

FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
BPE_VOCAB = "bpe.vocab"
MIN_SECONDS = 1.0  # shorter inputs hallucinate (P-1); pad with silence
MIN_MEAN_CONF = 0.5  # a result whose words all sit below this is a filler on noise ("Uh" at 0.36); speech is ~1.0
DOWNLOAD = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
            "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2")


def write_bpe_vocab(tokens_txt: Path, dest: Path) -> Path:
    """`bpe.vocab` for sherpa-onnx's sentencepiece encoder from `tokens.txt` (piece<TAB>score). Longer pieces
    score higher so a hotword is encoded with its whole-word piece when one exists (P-1)."""
    lines = []
    for line in tokens_txt.read_text(encoding="utf-8").splitlines():
        piece, _, _ = line.rpartition(" ")
        if not piece or piece.startswith("<"):
            continue
        lines.append(f"{piece}\t{-1.0 / len(piece):.4f}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def words_from(tokens, timestamps, durations, log_probs) -> list[Word]:
    """Token → word rule: a piece starting with a space (or `▁`) opens a word; others extend the current one."""
    out: list[list] = []  # [text, start, end, [log_probs]]
    stamps, durs, lps = list(timestamps or []), list(durations or []), list(log_probs or [])
    for k, tok in enumerate(tokens):
        start = stamps[k] if k < len(stamps) else None
        end = start + durs[k] if (start is not None and k < len(durs)) else start
        lp = lps[k] if k < len(lps) else None
        text = tok.lstrip("▁ ")
        if tok.startswith(("▁", " ")) or not out:
            out.append([text, start, end, [lp] if lp is not None else []])
        else:
            cur = out[-1]
            cur[0] += text
            cur[2] = end if end is not None else cur[2]
            if lp is not None:
                cur[3].append(lp)
    result = []
    for text, start, end, probs in out:
        if not text:
            continue
        conf = math.exp(sum(probs) / len(probs)) if probs else None
        result.append(Word(text, start, end, None if conf is None else round(min(1.0, conf), 4)))
    return result


class SherpaAsr:
    def __init__(self, settings) -> None:
        self.model_dir = Path(settings.asr_model_dir)
        self.hotwords_enabled = str(getattr(settings, "asr_hotwords", "off")) != "off"
        self.num_threads = int(getattr(settings, "asr_threads", 4))
        self._rec = None

    def _load(self):
        if self._rec is None:
            import sherpa_onnx  # lazy

            d = self.model_dir
            kw = {}
            if self.hotwords_enabled:
                vocab = d / BPE_VOCAB
                if not vocab.exists():
                    write_bpe_vocab(d / FILES[3], vocab)
                kw = dict(decoding_method="modified_beam_search", modeling_unit="bpe", bpe_vocab=str(vocab),
                          hotwords_score=1.5)
            self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(d / FILES[0]), decoder=str(d / FILES[1]), joiner=str(d / FILES[2]),
                tokens=str(d / FILES[3]), model_type="nemo_transducer", num_threads=self.num_threads, **kw)
        return self._rec

    async def transcribe(self, pcm: bytes, sample_rate: int, hotwords: list[str] | None = None) -> list[Word]:
        if hotwords and not self.hotwords_enabled:
            raise NotImplementedError("ASR hotwords are off (ASR_HOTWORDS=off, ADR-0011)")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, pcm, sample_rate, hotwords)

    def _run(self, pcm: bytes, sample_rate: int, hotwords: list[str] | None) -> list[Word]:
        import numpy as np

        rec = self._load()
        samples = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
        short = int(sample_rate * MIN_SECONDS) - len(samples)
        if short > 0:
            samples = np.concatenate([samples, np.zeros(short, dtype="float32")])
        stream = rec.create_stream("/".join(hotwords)) if hotwords else rec.create_stream()
        stream.accept_waveform(sample_rate, samples)
        rec.decode_stream(stream)
        res = stream.result
        out = words_from(res.tokens, getattr(res, "timestamps", None), getattr(res, "durations", None),
                         getattr(res, "ys_log_probs", None))
        confs = [w.conf for w in out if w.conf is not None]
        if confs and max(confs) < MIN_MEAN_CONF:
            return []  # noise decoded to a low-confidence filler (P-1); an empty result never repositions
        return out


def create(settings) -> SherpaAsr:
    return SherpaAsr(settings)


def status(settings) -> tuple[str, str]:
    if not has_package("sherpa_onnx"):
        return "missing package", "uv pip install --python .venv sherpa-onnx==1.13.8"
    d = Path(settings.asr_model_dir)
    if not all((d / f).exists() for f in FILES):
        return "missing model", f"python -m leafi doctor --download  (fetches {DOWNLOAD} into {d})"
    return "ok", ""
