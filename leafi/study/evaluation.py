"""Scoring for the reading evaluation (ADR-0013 → False-alarm budget; plan M4.4a).

One utterance reads one known text; each expected word carries a human label. `score_utterance` aligns the
heard words with ADR-0013 v2 and counts, per word, whether a candidate was created:

- `correct` label + candidate → false alarm (the budgeted rate: false alarms / correct content words);
- `error` label + candidate → hit, + no candidate → miss;
- `excluded` labels count in neither.

Pure: the caller supplies the ASR words and confidences, so the scoring is testable without audio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from leafi.core.text import norm
from leafi.core.wordinfo import WordInfo
from leafi.study.alignment import CandidateCreated, ReadingState, Unaligned, align

Label = Literal["correct", "error", "excluded"]


@dataclass
class Tally:
    utterances: int = 0
    skipped: int = 0  # label count did not match the tokenised text
    unaligned: int = 0
    correct: int = 0
    correct_content: int = 0
    false_alarms: int = 0
    false_alarms_content: int = 0
    errors: int = 0
    hits: int = 0
    conf_correct: list[float] = field(default_factory=list)  # ASR confidence of words heard at correct tokens
    conf_false: list[float] = field(default_factory=list)  # ... at false-alarm tokens
    false_alarm_pairs: list[tuple[str, str | None]] = field(default_factory=list)  # (expected, heard)

    def add(self, other: Tally) -> None:
        for k, v in vars(other).items():
            if isinstance(v, list):
                getattr(self, k).extend(v)
            else:
                setattr(self, k, getattr(self, k) + v)

    @property
    def false_alarm_rate(self) -> float | None:
        return self.false_alarms_content / self.correct_content if self.correct_content else None

    @property
    def miss_rate(self) -> float | None:
        return (self.errors - self.hits) / self.errors if self.errors else None


def score_utterance(text: str, labels: list[Label], words: list[str], confs: list[float | None],
                    info: WordInfo) -> Tally:
    t = Tally(utterances=1)
    st = ReadingState.from_text(text)
    if st.n != len(labels):
        t.utterances, t.skipped = 0, 1
        return t
    st2, obs, events = align(st, words, 1, info, confs=confs)
    if any(isinstance(e, Unaligned) for e in events):
        t.unaligned = 1
    cand = {e.token_index for e in events if isinstance(e, CandidateCreated)}
    heard_conf = _token_confs(obs, [norm(w) for w in words if norm(w)], [c for w, c in zip(words, confs,
                                                                                          strict=True) if norm(w)])
    for i, (tok, lab) in enumerate(zip(st.tokens, labels, strict=True)):
        if lab == "correct":
            t.correct += 1
            t.correct_content += not tok.function_word
            if i in cand:
                t.false_alarms += 1
                t.false_alarms_content += not tok.function_word
                heard = next((o.heard for o in obs if o.token_start == i and o.kind != "inserted"), None)
                t.false_alarm_pairs.append((tok.norm, heard))
                if heard_conf.get(i) is not None:
                    t.conf_false.append(heard_conf[i])
            elif heard_conf.get(i) is not None:
                t.conf_correct.append(heard_conf[i])
        elif lab == "error":
            t.errors += 1
            t.hits += i in cand
    return t


def diagnose_unaligned(text: str, words: list[str], confs: list[float | None], info: WordInfo) -> dict:
    """Why `align` found no accepted path for this utterance (TD-28): `empty` (the ASR heard nothing),
    `ceiling` (a pass has an anchor but its internal cost exceeds the per-word ceiling), `no_anchor` (no pass
    has an anchor even without the ceiling), split by `short` (m ≤ 2) where rules (c) and (d) apply."""
    from leafi.study import alignment as al

    st = ReadingState.from_text(text)
    w, c = al._heard(words, confs)
    m = len(w)
    if m == 0:
        return {"reason": "empty", "m": 0}
    pairs = al._pairs(w, st.tokens, info)
    out = {"m": m}
    anchor_any, ceiling_hit = False, False
    saved = al.CEILING_PER_WORD
    try:
        for page in (False, True):
            if page and m < 2:
                continue
            p = al.best_path(st, w, info, page=page, pairs=pairs)
            if p is None:
                continue
            tag = "page" if page else "fast"
            matched = [o for o in p.ops if o.op in ("align", "join") and o.cls in al.MATCHED]
            out[f"{tag}_internal_per_word"] = round(p.internal / m, 1)
            out[f"{tag}_matched"] = sum(o.k for o in matched)
            al.CEILING_PER_WORD = 10**6
            anchored = al._accepted(st, p, w, c, page, info, frozenset())
            al.CEILING_PER_WORD = saved
            anchor_any |= anchored
            ceiling_hit |= anchored and m >= 3 and p.internal > saved * m
    finally:
        al.CEILING_PER_WORD = saved
    if anchor_any and ceiling_hit:
        reason = "ceiling"
    elif anchor_any:
        reason = "other"  # anchored and under the ceiling in some pass, yet not chosen (should not happen)
    else:
        reason = "no_anchor_short" if m <= 2 else "no_anchor"
    out["reason"] = reason
    return out


def _token_confs(obs, words: list[str], confs: list[float | None]) -> dict[int, float | None]:
    """Walk the observations in path order, consuming heard words, to find each token's heard confidence."""
    out: dict[int, float | None] = {}
    j = 0
    for o in obs:
        if o.kind == "unaligned":
            j += o.word_count or 0
        elif o.kind in ("matched", "substituted", "inserted"):
            k = len(o.heard.split()) if o.heard else 1
            if o.kind != "inserted" and j < len(confs):
                out.setdefault(o.token_start, confs[j])
            j += k
    return out
