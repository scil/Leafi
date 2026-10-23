"""Reading evaluation on public data (ADR-0013 → False-alarm budget; plan M4.4a).

    .venv\\Scripts\\python scripts/evals/reading_eval.py --set speechocean762 [--max-age 12] [--limit N]

speechocean762 (OpenSLR SLR101, CC BY 4.0; Zhang et al., "speechocean762: An Open-Source Non-native English
Speech Corpus For Pronunciation Assessment", Interspeech 2021) is fetched by
`python -m leafi doctor --download --only speechocean762`. Each utterance is one read sentence; five experts
scored every word 0–10. A word scored ≥ 7 was said correctly (possibly accented), 0–3 is a reading error
("mispronounced into some other word" or "missed"), 4–6 is excluded. Audio → Parakeet (the study ASR) →
ADR-0013 v2 `align` with the local WordInfo → candidates, counted by `leafi.study.evaluation`.

Runs offline and speaks nowhere. Results go to stdout and `data/evals/results/` (gitignored).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leafi.core.config import Settings  # noqa: E402
from leafi.study.evaluation import Tally, diagnose_unaligned, score_utterance  # noqa: E402

LEVERS = ("ANCHOR_CONF", "LOW_CONF", "RETRY_MIN_CONF", "TRIGGER_PER_WORD", "CEILING_PER_WORD", "PAGE_MARGIN",
          "ANCHOR_MATCH_SHARE", "LONE_ANCHOR_MAX_M")
ATTRIBUTION = ("speechocean762 (OpenSLR SLR101), CC BY 4.0, Zhang et al., Interspeech 2021; "
               "used unmodified for evaluation")


def _label(score: float) -> str:
    return "correct" if score >= 7 else "error" if score <= 3 else "excluded"


def _ages(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in root.rglob("spk2age"):
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                out[parts[0]] = int(parts[1])
    return out


def _utt2spk(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in root.rglob("utt2spk"):
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                out[parts[0]] = parts[1]
    return out


def _read_wav(p: Path) -> tuple[bytes, int]:
    with wave.open(str(p), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{p.name}: expected 16-bit mono")
        return w.readframes(w.getnframes()), w.getframerate()


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def _asr_cache(settings: Settings, root: Path, wavs: dict[str, Path], utts: list[str]) -> dict[str, list]:
    """Parakeet's words and confidences per utterance, computed once and kept in
    `data/evals/results/asr-speechocean762.json` (gitignored): alignment levers then rerun in seconds."""
    path = Path(settings.data_dir) / "evals" / "results" / "asr-speechocean762.json"
    key = str(settings.asr_model_dir)
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if cache.get("model") != key:
        cache = {"model": key, "utts": {}}
    missing = [u for u in utts if u not in cache["utts"] and u in wavs]
    if missing:
        from leafi.services.asr import sherpa

        asr = sherpa.create(settings)
        for u in missing:
            pcm, rate = _read_wav(wavs[u])
            cache["utts"][u] = [[w.text, w.conf] for w in asr._run(pcm, rate, None)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache), encoding="utf-8")
    return cache["utts"]


def run(settings: Settings, max_age: int | None, limit: int | None, diagnose: bool = False) -> dict:
    from leafi.services.wordinfo import LocalWordInfo

    root = Path(settings.data_dir) / "evals" / "speechocean762"
    scores_path = root / "resource" / "scores.json"
    if not scores_path.exists():
        raise SystemExit("speechocean762 missing: python -m leafi doctor --download --only speechocean762")
    scores = json.loads(scores_path.read_text(encoding="utf-8"))
    wavs = {p.stem: p for p in root.rglob("*.WAV")} | {p.stem: p for p in root.rglob("*.wav")}
    ages, spk = _ages(root), _utt2spk(root)
    picked = []
    for utt in sorted(scores):
        age = ages.get(spk.get(utt, ""))
        if (max_age is not None and (age is None or age > max_age)) or utt not in wavs:
            continue
        picked.append(utt)
        if limit and len(picked) >= limit:
            break
    t0 = time.perf_counter()
    heard_all = _asr_cache(settings, root, wavs, picked)
    t_asr = time.perf_counter() - t0
    info = LocalWordInfo(settings.models_dir)
    total, kids = Tally(), Tally()
    reasons: Counter = Counter()
    examples: dict[str, list] = {}
    for utt in picked:
        rec, age = scores[utt], ages.get(spk.get(utt, ""))
        words = [w for w, _ in heard_all[utt]]
        confs = [c for _, c in heard_all[utt]]
        labels = [_label(w["accuracy"]) for w in rec["words"]]
        t = score_utterance(rec["text"], labels, words, confs, info)
        total.add(t)
        if age is not None and age <= 12:
            kids.add(t)
        if diagnose and t.unaligned:
            d = diagnose_unaligned(rec["text"], words, confs, info)
            r = d["reason"] + ("" if all(lab == "correct" for lab in labels) else " (some words scored < 7)")
            reasons[r] += 1
            ex = examples.setdefault(d["reason"], [])
            if len(ex) < 8:
                ex.append({"utt": utt, "text": rec["text"], "heard": " ".join(words), **d})
    out = {"set": "speechocean762", "attribution": ATTRIBUTION, "max_age": max_age,
           "seconds": round(time.perf_counter() - t0, 1), "asr_seconds": round(t_asr, 1),
           "word_info": info.versions, "all": _summary(total), "children_le_12": _summary(kids)}
    if diagnose:
        out["unaligned_reasons"] = dict(reasons.most_common())
        out["unaligned_examples"] = examples
    return out


def _summary(t: Tally) -> dict:
    return {
        "utterances": t.utterances, "skipped_label_mismatch": t.skipped, "unaligned_utterances": t.unaligned,
        "correct_words": t.correct, "correct_content_words": t.correct_content,
        "false_alarms": t.false_alarms, "false_alarms_content": t.false_alarms_content,
        "false_alarm_rate_content": None if t.false_alarm_rate is None else round(t.false_alarm_rate, 4),
        "error_words": t.errors, "hits": t.hits,
        "miss_rate": None if t.miss_rate is None else round(t.miss_rate, 4),
        "asr_conf_correct_p10_p50_p90": [_pct(t.conf_correct, q) for q in (0.1, 0.5, 0.9)],
        "asr_conf_false_alarm_p10_p50_p90": [_pct(t.conf_false, q) for q in (0.1, 0.5, 0.9)],
        "asr_conf_correct_mean": round(statistics.fmean(t.conf_correct), 3) if t.conf_correct else None,
        "false_alarm_kinds": _kinds(t.false_alarm_pairs),
        "top_false_alarm_pairs": Counter(f"{e}->{h}" for e, h in t.false_alarm_pairs).most_common(25),
    }


def _kinds(pairs: list[tuple[str, str | None]]) -> dict[str, int]:
    """What the false alarms are: a deletion (nothing heard), or a substitution."""
    return dict(Counter("deletion" if h is None else "substitution" for _, h in pairs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", choices=["speechocean762"], default="speechocean762")
    ap.add_argument("--max-age", type=int, default=None, help="only speakers up to this age")
    ap.add_argument("--limit", type=int, default=None, help="stop after N utterances")
    ap.add_argument("--diagnose", action="store_true", help="classify why each unaligned utterance failed")
    ap.add_argument("--set-const", action="append", default=[], metavar="NAME=VALUE",
                    help="override one ADR-0013 threshold for this run only (a lever experiment; TD-28)")
    args = ap.parse_args()
    from leafi.study import alignment

    levers = {}
    for item in args.set_const:
        name, _, value = item.partition("=")
        if name not in LEVERS:
            raise SystemExit(f"--set-const: {name} is not one of {', '.join(LEVERS)}")
        levers[name] = type(getattr(alignment, name))(value)
        setattr(alignment, name, levers[name])
    settings = Settings()
    from leafi import bootstrap

    bootstrap.install(settings)  # the socket guard before any service (M5 design D2)
    out = run(settings, args.max_age, args.limit, args.diagnose)
    out["overrides"] = levers
    # the untuned thresholds this run used, so runs can be compared lever by lever (TD-28)
    out["thresholds"] = {k: getattr(alignment, k) for k in LEVERS}
    print(json.dumps(out, indent=2))
    res = Path(settings.data_dir) / "evals" / "results"
    res.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (res / f"reading-eval-{args.set}-{stamp}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
