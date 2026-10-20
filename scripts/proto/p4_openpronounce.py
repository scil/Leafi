"""Prototype P-4: OpenPronounce offline smoke test (no network, Kokoro reference voice, gTTS off).

Plan → Prototypes: confirm the wiring in `leafi/services/pronunciation/openpronounce.py` runs with
`LEAFI_NO_NETWORK=1`, measure one-word scoring latency (budget: ≤ 1 s GPU / 3 s CPU, performance.md), and
look at the score separation on synthetic cases (a Kokoro voice different from the reference voice reads the
expected word, a near-miss, an unrelated word). The parent-labelled child-speech evaluation that gates
`PRON_AUTO_JUDGE` is a separate protocol (docs/engineering/pronunciation-evaluation.md).

Run (nothing is played anywhere):
    $env:LEAFI_NO_NETWORK="1"; .venv\\Scripts\\python scripts/proto/p4_openpronounce.py
    $env:LEAFI_NO_NETWORK="1"; .venv\\Scripts\\python scripts/proto/p4_openpronounce.py --eval data/evals/retries.csv
The second form scores a parent-labelled retry set (columns: expected, path, label ∈ ok|wrong|unclear) and
prints the false-correction table per threshold (docs/engineering/pronunciation-evaluation.md).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leafi.core.config import Settings  # noqa: E402
from leafi.core.ports import AudioRef  # noqa: E402

CASES = [  # (expected word, what the "learner" voice says)
    ("through", "through"),
    ("through", "threw"),
    ("through", "thorough"),
    ("through", "banana"),
    ("little", "little"),
    ("little", "lid dull"),
    ("brown", "brown"),
    ("brown", "crown"),
]


THRESHOLDS = (0.3, 0.4, 0.5, 0.6)


def pcm16_of(path: Path) -> bytes:
    import numpy as np
    import soxr

    from leafi.core.audio import read_wav

    pcm, sr, ch = read_wav(path)
    x = np.frombuffer(pcm, dtype="<i2").astype("float32")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return soxr.resample(x, sr, 16000).astype("<i2").tobytes() if sr != 16000 else x.astype("<i2").tobytes()


async def evaluate(csv_path: Path, settings: Settings) -> None:
    from leafi.services import pronunciation

    scorer = pronunciation.REGISTRY.create("openpronounce", settings)
    rows = [r for r in csv.DictReader(csv_path.open(encoding="utf-8", newline=""))]
    out_rows = []
    for r in rows:
        label = (r.get("label") or "").strip().lower()
        if label not in ("ok", "wrong"):
            out_rows.append({**r, "score": "", "phones_expected": "", "phones_heard": ""})
            continue
        res = await scorer.score(AudioRef(pcm16_of(Path(r["path"]))), r["expected"])
        out_rows.append({**r, "score": f"{res.score:.3f}" if res else "", "phones_expected": res.phonemes_expected if res else "",
                         "phones_heard": res.phonemes_heard if res else ""})
    out = csv_path.with_name("scores.csv")
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else ["expected", "path", "label", "score"])
        w.writeheader()
        w.writerows(out_rows)
    ok = [float(r["score"]) for r in out_rows if r.get("label", "").lower() == "ok" and r["score"]]
    wrong = [float(r["score"]) for r in out_rows if r.get("label", "").lower() == "wrong" and r["score"]]
    unclear = sum(1 for r in rows if (r.get("label") or "").strip().lower() == "unclear")
    print(f"\nrows: ok {len(ok)}, wrong {len(wrong)}, unclear {unclear} (excluded); scores written to {out}")
    print("\n| threshold | flagged | false corrections | rate | misses | miss rate |\n|---|---|---|---|---|---|")
    for t in THRESHOLDS:
        fc = sum(1 for s in ok if s < t)
        miss = sum(1 for s in wrong if s >= t)
        n = len(ok) + len(wrong)
        print(f"| {t:.1f} | {n} | {fc} | {fc / max(1, len(ok)):.1%} | {miss} | {miss / max(1, len(wrong)):.1%} |")
    for name, xs in (("ok", ok), ("wrong", wrong)):
        if xs:
            q = statistics.quantiles(xs, n=4) if len(xs) >= 4 else [min(xs), statistics.median(xs), max(xs)]
            print(f"{name}: min {min(xs):.2f} quartiles {[round(v, 2) for v in q]} max {max(xs):.2f}")
    print("gate: ≥ 40 flagged rows and false-correction rate ≤ 15 % at the chosen threshold (ADR-0011)")


async def main() -> None:
    from leafi.core import netguard
    from leafi.core.audio import read_wav
    from leafi.services import pronunciation, tts

    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", type=Path, help="parent-labelled retry CSV (expected, path, label)")
    args = ap.parse_args()
    if os.environ.get("LEAFI_NO_NETWORK") == "1":
        netguard.install()
        print("LEAFI_NO_NETWORK=1: non-loopback connects raise")
    settings = Settings(_env_file=None, cache_dir=Path(tempfile.mkdtemp(prefix="p4-")), tts_voice_en_kokoro="af_heart")
    if args.eval:
        await evaluate(args.eval, settings)
        return
    learner_voice = Settings(_env_file=None, cache_dir=settings.cache_dir / "learner", tts_voice_en_kokoro="am_adam")
    print("pronunciation status:", pronunciation.REGISTRY.status("openpronounce", settings))
    scorer = pronunciation.REGISTRY.create("openpronounce", settings)
    speaker = tts.create(learner_voice, en="kokoro", zh="kokoro")

    import soxr
    import numpy as np

    print("\n| expected | learner says | score | latency s | heard phones |")
    print("|---|---|---|---|---|")
    first = True
    for expected, said in CASES:
        clip = await speaker.synth(said, "en")
        pcm, sr, _ = read_wav(clip.path)
        x = np.frombuffer(pcm, dtype="<i2").astype("float32")
        pcm16 = soxr.resample(x, sr, 16000).astype("<i2").tobytes() if sr != 16000 else pcm
        t0 = time.perf_counter()
        res = await scorer.score(AudioRef(pcm16), expected)
        dt = time.perf_counter() - t0
        note = " (first call: model load)" if first else ""
        first = False
        print(f"| {expected} | {said} | {res.score:.2f} | {dt:.2f}{note} | {res.phonemes_heard} |")
    import torch

    print(f"\ntorch device: {'cuda' if torch.cuda.is_available() else 'cpu'}; "
          f"OPENPRONOUNCE_TTS={os.environ.get('OPENPRONOUNCE_TTS')} HF_HUB_OFFLINE={os.environ.get('HF_HUB_OFFLINE')}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
