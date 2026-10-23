"""Reading alignment and the pure reading-state rules. ADR-0013 (v2) is the only owner of these rules; this
module implements its pseudocode and must not add rules of its own (implementation choices are in the plan's
Decision log).

Costs are integers in tenths (ADR-0013): exact / phones / join 0, fuzzy 3, inflection / substitute 10,
delete run 8 + 3·(L − 1), insert 12, back jump 4 + (a − k), boundary 5 per visit, page entry 15, sentence
skip 15. The DP packs the first tie-break keys into one integer, `cost·K² + insertions·K + jumps`, so a
plain minimum orders by cost, then insertions, then jumps; the distance of the first aligned token from
`pcur` is compared at the entry, and the lexicographic rule decides the rest during reconstruction.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from rapidfuzz import fuzz, process

from leafi.core.text import NUMBER_WORDS, TextToken, canonical_number, norm, numeral_readings, sim, tokenize
from leafi.core.wordinfo import NullWordInfo, WordInfo
from leafi.study.function_words import FUNCTION_WORDS, INTERJECTIONS

Status = Literal["unattempted", "provisional", "committed", "candidate", "settled", "unread"]

C_FUZZY, C_SUB, C_DEL0, C_DELX, C_INS, C_JUMP0, C_BOUND, C_PAGE_ENTRY, C_SKIP_SENT = 3, 10, 8, 3, 12, 4, 5, 15, 15
PAGE_MARGIN, TRIGGER_PER_WORD, CEILING_PER_WORD = 10, 5, 7
ANCHOR_MATCH_SHARE = 0.5  # rule 4(b): matched ≥ ceil(share · m)
LONE_ANCHOR_MAX_M = 2  # rule 4(c): a lone matched token anchors an utterance of at most this many words
# LOW_CONF 0.9: owner decision 2026-10-22 from the speechocean762 run (false-alarm words median 0.82, correct
# words 0.998); its effect on false alarms and hits is not yet measured (TD-28).
ANCHOR_CONF, LOW_CONF, RETRY_MIN_CONF = 0.8, 0.9, 0.5
FUZZY_SIM = 0.80
LINE_SKIP_MIN = 4
UNALIGNED_PROMPT_RUN, UNALIGNED_PROMPT_WORDS = 3, 6
MAX_JOIN = 4

K = 1024
K2 = K * K
INF = 1 << 60

# Pair classes and their rank in the lexicographic operation order (ADR-0013 rule 3).
EXACT, PHONES, FUZZY, JOIN, INFLECTION, SUBSTITUTE = "exact", "phones", "fuzzy", "join", "inflection", "substitute"
_CLS = [EXACT, PHONES, FUZZY, INFLECTION, SUBSTITUTE]  # codes 0..4 in the pair matrix
_COST = {EXACT: 0, PHONES: 0, FUZZY: C_FUZZY, INFLECTION: C_SUB, SUBSTITUTE: C_SUB}
RANK = {EXACT: 0, PHONES: 1, FUZZY: 2, JOIN: 3, INFLECTION: 4, SUBSTITUTE: 4, "delete": 5, "insert": 6, "jump": 7}
MATCHED = {EXACT, PHONES, FUZZY, JOIN}


# ---------------------------------------------------------------- state


@dataclass
class Tok:
    text: str
    norm: str
    start: int
    end: int
    sentence_id: int
    status: Status = "unattempted"
    created_by: int | None = None  # utterance seq that created the candidate at this token
    miscue_id: int | None = None  # the candidate's miscue row; carried through corrections
    function_word: bool = False
    supplied: bool = False  # a told word: alignment never withdraws it (ADR-0013 → Supplying a word)

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)


@dataclass
class ReadingState:
    tokens: list[Tok]
    pcur: int = 0
    ccur: int = 0
    completed: set[int] = field(default_factory=set)
    turn_id: int = 0
    page_read_id: int | None = None
    revision_id: int | None = None
    unaligned_run: int = 0
    unaligned_words: int = 0
    prompted: bool = False

    # ---- construction / persistence
    @classmethod
    def from_text(cls, text: str, **kw) -> ReadingState:
        return cls.from_tokens(tokenize(text), **kw)

    @classmethod
    def from_tokens(cls, toks: list[TextToken], **kw) -> ReadingState:
        return cls([Tok(t.text, t.norm, t.start, t.end, t.sentence_id, function_word=t.norm in FUNCTION_WORDS)
                    for t in toks], **kw)

    def to_json(self) -> dict:
        return {
            "status": [t.status for t in self.tokens],
            "created_by": [t.created_by for t in self.tokens],
            "miscue_id": [t.miscue_id for t in self.tokens],
            "supplied": [i for i, t in enumerate(self.tokens) if t.supplied],
            "pcur": self.pcur, "ccur": self.ccur, "completed": sorted(self.completed),
            "turn_id": self.turn_id, "page_read_id": self.page_read_id, "revision_id": self.revision_id,
            "unaligned_run": self.unaligned_run, "unaligned_words": self.unaligned_words,
            "prompted": self.prompted,
        }

    @classmethod
    def from_json(cls, text: str, data: dict) -> ReadingState:
        st = cls.from_text(text, page_read_id=data.get("page_read_id"), revision_id=data.get("revision_id"))
        ids = data.get("miscue_id") or [None] * len(st.tokens)
        for t, s, c, mid in zip(st.tokens, data["status"], data["created_by"], ids, strict=True):
            t.status, t.created_by, t.miscue_id = s, c, mid
        for i in data.get("supplied", []):
            st.tokens[i].supplied = True
        st.pcur, st.ccur = data["pcur"], data["ccur"]
        st.completed = set(data["completed"])
        st.turn_id = data["turn_id"]
        st.unaligned_run = data.get("unaligned_run", 0)
        st.unaligned_words = data.get("unaligned_words", 0)
        st.prompted = data.get("prompted", False)
        return st

    # ---- sentence geometry
    @property
    def n(self) -> int:
        return len(self.tokens)

    def sentence_ids(self) -> list[int]:
        return sorted({t.sentence_id for t in self.tokens})

    def first_index(self, sid: int) -> int:
        return next(i for i, t in enumerate(self.tokens) if t.sentence_id == sid)

    def last_index(self, sid: int) -> int:
        return max(i for i, t in enumerate(self.tokens) if t.sentence_id == sid)

    def sentence_start(self, i: int) -> int:
        if i >= self.n:
            return self.n
        return self.first_index(self.tokens[i].sentence_id)

    def current_sentence(self) -> int | None:
        """The sentence containing `pcur` (None when `pcur = n`)."""
        return self.tokens[self.pcur].sentence_id if self.pcur < self.n else None

    def statuses(self) -> str:
        """Compact status string for tests: U P C M S R."""
        code = {"unattempted": "U", "provisional": "P", "committed": "C", "candidate": "M", "settled": "S",
                "unread": "R"}
        return " ".join(code[t.status] for t in self.tokens)

    def page_complete(self) -> bool:
        return set(self.sentence_ids()) <= self.completed


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class Observation:
    kind: Literal["matched", "substituted", "deleted", "inserted", "unaligned"]
    token_start: int | None
    token_end: int | None
    heard: str | None = None
    sim: float | None = None
    pair_class: str | None = None
    function_word: bool = False
    repeat: bool = False
    self_correction: bool = False
    word_count: int | None = None


@dataclass(frozen=True)
class SentenceReached:
    sentence_id: int


@dataclass(frozen=True)
class Unaligned:
    count: int


@dataclass(frozen=True)
class FirstWordsPrompt:
    pass


@dataclass(frozen=True)
class LineSkipped:
    count: int
    token_start: int
    token_end: int


@dataclass(frozen=True)
class CandidateCreated:
    token_index: int
    expected: str
    heard: str | None
    observation_index: int | None
    origin: Literal["substitution", "deletion", "supplied"] = "substitution"


@dataclass(frozen=True)
class CandidateWithdrawn:
    token_index: int
    reason: Literal["self_corrected", "reread"]


@dataclass(frozen=True)
class OriginSupplied:
    """A hint on a token that already was a candidate: its miscue's origin becomes `supplied`."""

    token_index: int


Event = (SentenceReached | Unaligned | FirstWordsPrompt | LineSkipped | CandidateCreated | CandidateWithdrawn
         | OriginSupplied)


# ---------------------------------------------------------------- pair classes


@dataclass
class _Pairs:
    cls: np.ndarray  # m × n codes into _CLS
    cost: np.ndarray  # m × n tenths
    sim: np.ndarray  # m × n 0..100
    join: dict[int, np.ndarray]  # k → m × n bool: words j..j+k−1 join onto token u


def pair_class(heard: str, tok: Tok, info: WordInfo) -> str:
    """ADR-0013 → Pair classes for one pair, first match wins (the reference the matrix must equal)."""
    if heard == tok.norm or heard in numeral_readings(tok.text):
        return EXACT
    ph = info.phones(heard)
    if ph and ph & info.phones(tok.norm):
        return PHONES
    if heard != tok.norm and info.is_word(heard) and info.is_word(tok.norm) and \
            info.lemmas(heard) & info.lemmas(tok.norm):
        return INFLECTION
    if sim(heard, tok.norm) >= FUZZY_SIM and not info.is_word(heard):
        return FUZZY
    return SUBSTITUTE


def _join_key(words: list[str], j: int, k: int) -> str | None:
    seg = words[j:j + k]
    if len(seg) != k or seg[0] == "and" or seg[-1] == "and":
        return None
    if any(w not in NUMBER_WORDS and w != "and" for w in seg):
        return None
    return canonical_number(" ".join(seg))


def _pairs(words: list[str], toks: list[Tok], info: WordInfo) -> _Pairs:
    m, n = len(words), len(toks)
    norms = [t.norm for t in toks]
    s = process.cdist(words, norms, scorer=fuzz.ratio, dtype=np.int32, workers=1) if n else \
        np.zeros((m, 0), np.int32)
    by_norm: dict[str, list[int]] = {}
    by_reading: dict[str, list[int]] = {}
    by_phone: dict[str, list[int]] = {}
    by_lemma: dict[str, list[int]] = {}
    for i, t in enumerate(toks):
        by_norm.setdefault(t.norm, []).append(i)
        for r in numeral_readings(t.text):
            by_reading.setdefault(r, []).append(i)
        for p in info.phones(t.norm):
            by_phone.setdefault(p, []).append(i)
        if info.is_word(t.norm):
            for lem in info.lemmas(t.norm):
                by_lemma.setdefault(lem, []).append(i)
    cls = np.full((m, n), 4, np.int8)
    nonword = np.array([not info.is_word(w) for w in words], bool)[:, None]
    cls[(s >= FUZZY_SIM * 100) & nonword] = 2
    for j, w in enumerate(words):
        if info.is_word(w):
            for lem in info.lemmas(w):
                for i in by_lemma.get(lem, ()):
                    if norms[i] != w:
                        cls[j, i] = 3
        for p in info.phones(w):
            for i in by_phone.get(p, ()):
                cls[j, i] = 1
        for i in by_norm.get(w, ()):
            cls[j, i] = 0
        for i in by_reading.get(w, ()):
            cls[j, i] = 0
    # inflection outranks fuzzy, phones outranks inflection, exact outranks all (first match wins)
    cost = np.array([_COST[c] for c in _CLS], np.int64)[cls]
    join: dict[int, np.ndarray] = {}
    for k in range(2, MAX_JOIN + 1):
        arr = np.zeros((m, n), bool)
        for j in range(m - k + 1):
            key = _join_key(words, j, k)
            if key is not None:
                for i in by_reading.get(key, ()):
                    arr[j, i] = True
        if arr.any():
            join[k] = arr
    return _Pairs(cls, cost, s, join)


# ---------------------------------------------------------------- DP


@dataclass(frozen=True)
class Op:
    op: Literal["align", "join", "delete", "insert", "jump"]
    index: int  # expected index (insert: anchor = next expected index)
    word: int | None = None  # first heard word
    k: int = 1  # heard words consumed (join: 2..4)
    cls: str | None = None


@dataclass
class Path:
    ops: list[Op]
    cost: int
    entry: int
    boundary: int
    insertions: int
    jumps: int
    first: int

    @property
    def internal(self) -> int:
        return self.cost - self.entry - self.boundary


def _seg_prefix_min(x: np.ndarray, bounds: list[tuple[int, int]]) -> np.ndarray:
    out = np.empty_like(x)
    for a, b in bounds:
        out[a:b] = np.minimum.accumulate(x[a:b])
    return out


def _seg_suffix_min(x: np.ndarray, bounds: list[tuple[int, int]]) -> np.ndarray:
    out = np.empty_like(x)
    for a, b in bounds:
        out[a:b] = np.minimum.accumulate(x[a:b][::-1])[::-1]
    return out


class _DP:
    """Backward DP over a window of tokens (global indices lo..hi−1) for all heard words.

    State after `j` words with the last aligned token `t`: `c` = 1 or ≥ 2 aligned tokens in the open visit,
    flag A (last op aligned: a back jump may follow) or I (last op an insertion). Values are packed keys of
    the cost to go, the visit's closing charge included."""

    def __init__(self, st: ReadingState, words: list[str], pairs: _Pairs, lo: int, hi: int, page: bool,
                 pcur: int, entry: np.ndarray) -> None:
        self.st, self.words, self.lo, self.hi, self.page, self.pcur = st, words, lo, hi, page, pcur
        m, w = len(words), hi - lo
        self.m, self.w = m, w
        sid = np.array([t.sentence_id for t in st.tokens[lo:hi]], np.int64)
        self.sid = sid
        full_len: dict[int, int] = {}
        for t in st.tokens:
            full_len[t.sentence_id] = full_len.get(t.sentence_id, 0) + 1
        self.charge1 = np.array([C_BOUND * K2 if full_len[x] >= 2 else 0 for x in sid], np.int64)
        starts = [0] + [i for i in range(1, w) if sid[i] != sid[i - 1]] + [w]
        self.bounds = list(zip(starts[:-1], starts[1:], strict=True))
        self.seg_of = np.zeros(w, np.int64)
        for g, (a, b) in enumerate(self.bounds):
            self.seg_of[a:b] = g
        self.seg_start = np.array([self.bounds[g][0] for g in self.seg_of], np.int64)
        self.seg_end = np.array([self.bounds[g][1] for g in self.seg_of], np.int64)
        self.P = pairs.cost[:, lo:hi] * K2
        self.cls = pairs.cls[:, lo:hi]
        self.J = {k: np.where(a[:, lo:hi], 0, INF) for k, a in pairs.join.items()}
        self.entry = entry * K2
        self._backward()

    # value of arriving at token u with words starting at j (c' given), every way of consuming them
    def _arrive(self, j: int, c2: bool) -> np.ndarray:
        VA = self.VA2 if c2 else self.VA1
        out = self.P[j] + VA[j + 1]
        for k, J in self.J.items():
            if j + k <= self.m:
                out = np.minimum(out, J[j] + VA[j + k])
        return out

    def _backward(self) -> None:
        m, w = self.m, self.w
        idx = np.arange(w, dtype=np.int64)
        self.VA1 = [np.full(w, INF, np.int64) for _ in range(m + 1)]
        self.VA2 = [np.full(w, INF, np.int64) for _ in range(m + 1)]
        self.VI1 = [np.full(w, INF, np.int64) for _ in range(m + 1)]
        self.VI2 = [np.full(w, INF, np.int64) for _ in range(m + 1)]
        self.VA1[m] = self.charge1.copy()
        self.VI1[m] = self.charge1.copy()
        self.VA2[m] = np.zeros(w, np.int64)
        self.VI2[m] = np.zeros(w, np.int64)
        same_next = np.r_[self.sid[1:] == self.sid[:-1], False] if w else np.zeros(0, bool)
        for j in range(m - 1, 0, -1):
            b1, b2 = self._arrive(j, False), self._arrive(j, True)
            nxt1, nxt2 = np.r_[b1[1:], INF], np.r_[b2[1:], INF]
            # deletion runs to u >= t + 2: 3u − 3t + 2 (tenths), same sentence or a later one
            ss = _seg_suffix_min(b2 + 3 * K2 * idx, self.bounds)
            ss2 = np.full(w, INF, np.int64)
            ok = idx + 2 < self.seg_end
            ss2[ok] = ss[idx[ok] + 2]
            del_same = np.where(ok, ss2 - 3 * K2 * idx + 2 * K2, INF)
            gs = np.minimum.accumulate((b1 + 3 * K2 * idx)[::-1])[::-1]
            frm = np.maximum(idx + 2, self.seg_end)
            del_cross = np.where(frm < w, gs[np.minimum(frm, w - 1)] - 3 * K2 * idx + 2 * K2, INF)
            # back jumps (after an aligned token only), same sentence: 4 + t − k
            jp = _seg_prefix_min(b2 - K2 * idx, self.bounds) + K2 * (C_JUMP0 + idx) + 1
            jprev = np.full(w, INF, np.int64)
            if not self.page:
                segmin = np.array([np.min(b1[a:b] - K2 * idx[a:b]) for a, b in self.bounds], np.int64)
                prevmin = np.r_[INF, segmin[:-1]][self.seg_of]
                jprev = np.where(prevmin < INF, prevmin + K2 * (C_JUMP0 + idx) + 1, INF)
            for c in (1, 2):
                charge = self.charge1 if c == 1 else np.zeros(w, np.int64)
                VI = (self.VI1 if c == 1 else self.VI2)[j + 1]
                ins = VI + C_INS * K2 + K
                adv = np.where(same_next, nxt2, charge + nxt1)
                dl = np.minimum(del_same, charge + del_cross)
                base = np.minimum.reduce([ins, adv, dl])
                jump = np.minimum(jp, charge + jprev)
                a = np.minimum(base, jump)
                (self.VA1 if c == 1 else self.VA2)[j] = np.minimum(a, INF)
                (self.VI1 if c == 1 else self.VI2)[j] = np.minimum(base, INF)

    # ---- entry and reconstruction
    def best(self) -> Path | None:
        if self.w == 0 or self.m == 0:
            return None
        best_key, best_start = None, None
        for j0 in range(self.m):
            lead = C_INS * K2 * j0 + K * j0
            options = [(1, self.P[j0] + self.VA1[j0 + 1])]
            for k, J in self.J.items():
                if j0 + k <= self.m:
                    options.append((k, J[j0] + self.VA1[j0 + k]))
            for k, val in options:
                tot = val + self.entry + lead
                for f in np.flatnonzero(tot < INF):
                    v = int(tot[f])
                    cls_rank = RANK[JOIN] if k > 1 else RANK[_CLS[self.cls[j0, f]]]
                    key = (v // K2, abs(self.lo + int(f) - self.pcur), v % K2, int(f), j0, cls_rank, k)
                    if best_key is None or key < best_key:
                        best_key, best_start = key, (j0, int(f), k, v)
        if best_start is None:
            return None
        j0, f, k, total = best_start
        ops = [Op("insert", self.lo + f, j) for j in range(j0)]
        ops.append(self._align_op(j0, f, k))
        self._forward(ops, j0 + k, f, 1, True, self._V(j0 + k, f, 1, True))
        return self._summarise(ops, total, int(self.entry[f] // K2), f)

    def _align_op(self, j: int, u: int, k: int) -> Op:
        if k > 1:
            return Op("join", self.lo + u, j, k, JOIN)
        return Op("align", self.lo + u, j, 1, _CLS[self.cls[j, u]])

    def _V(self, j: int, t: int, c: int, flag_a: bool) -> int:
        if flag_a:
            return int((self.VA1 if c == 1 else self.VA2)[j][t])
        return int((self.VI1 if c == 1 else self.VI2)[j][t])

    def _arrivals(self, j: int, u: int):
        """(k, step cost of consuming, rank) for every way to consume words from j at token u."""
        out = [(1, int(self.P[j][u]), RANK[_CLS[self.cls[j, u]]])]
        for k, J in self.J.items():
            if j + k <= self.m and J[j][u] == 0:
                out.append((k, 0, RANK[JOIN]))
        return out

    def _forward(self, ops: list[Op], j: int, t: int, c: int, flag_a: bool, value: int) -> None:
        sid, m = self.sid, self.m
        while j < m:
            charge = int(self.charge1[t]) if c == 1 else 0
            cands = []  # (order key, step, next state, ops)

            def arrive(u: int, step0: int, order: tuple, pre_ops: tuple, same_c: bool,
                       j: int = j, charge: int = charge, cands: list = cands) -> None:
                for k, pc, rank in self._arrivals(j, u):
                    c2 = 2 if same_c else 1
                    pre = 0 if same_c else charge
                    v = step0 + pre + pc + self._V(j + k, u, c2, True)
                    cands.append((order + (rank, k), v, (j + k, u, c2), (pre_ops, u, k)))

            if flag_a:
                lowb = int(self.seg_start[t])
                if not self.page and self.seg_of[t] > 0:
                    lowb = self.bounds[int(self.seg_of[t]) - 1][0]
                for kk in range(lowb, t + 1):
                    arrive(kk, K2 * (C_JUMP0 + t - kk) + 1, (kk, RANK["jump"]), ("jump", kk), sid[kk] == sid[t])
            if t + 1 < self.w:
                arrive(t + 1, 0, (t + 1,), (), sid[t + 1] == sid[t])
            for u in range(t + 2, self.w):
                arrive(u, K2 * (C_DEL0 + C_DELX * (u - t - 2)), (t + 1, RANK["delete"], u), ("delete", t + 1),
                       sid[u] == sid[t])
            cands.append(((t + 1, RANK["insert"]), C_INS * K2 + K + self._V(j + 1, t, c, False),
                          (j + 1, t, c, False), None))
            cands.sort(key=lambda x: x[0])
            for _, v, nxt, spec in cands:
                if v == value:
                    if spec is None:
                        new_ops = [Op("insert", self.lo + t + 1, j)]
                    else:  # build the chosen candidate's operations only
                        pre_ops, u, k = spec
                        new_ops = []
                        if pre_ops and pre_ops[0] == "jump":
                            new_ops.append(Op("jump", self.lo + pre_ops[1]))
                        elif pre_ops:
                            new_ops.extend(Op("delete", self.lo + x) for x in range(pre_ops[1], u))
                        new_ops.append(self._align_op(j, u, k))
                    ops.extend(new_ops)
                    if len(nxt) == 4:
                        j, t, c, flag_a = nxt
                    else:
                        j, t, c = nxt
                        flag_a = True
                    value = self._V(j, t, c, flag_a)
                    break
            else:  # pragma: no cover - the backward values guarantee a match
                raise AssertionError("alignment reconstruction lost the optimum")

    def _summarise(self, ops: list[Op], total: int, entry: int, f: int) -> Path:
        st = self.st
        full_len: dict[int, int] = {}
        for t in st.tokens:
            full_len[t.sentence_id] = full_len.get(t.sentence_id, 0) + 1
        boundary, vis_sid, vis_count = 0, None, 0
        for o in ops:
            if o.op in ("align", "join"):
                s = st.tokens[o.index].sentence_id
                if s == vis_sid:
                    vis_count = min(vis_count + 1, 2)
                else:
                    if vis_sid is not None and vis_count < min(2, full_len[vis_sid]):
                        boundary += C_BOUND
                    vis_sid, vis_count = s, 1
        if vis_sid is not None and vis_count < min(2, full_len[vis_sid]):
            boundary += C_BOUND
        cost = total // K2
        rest = total % K2
        return Path(ops, int(cost), entry, boundary, int(rest // K), int(rest % K), self.lo + f)


def _fast_entry(st: ReadingState, lo: int, hi: int) -> np.ndarray:
    out = np.abs(np.arange(lo, hi) - st.pcur).astype(np.int64)
    if st.pcur >= st.n:
        return out
    cur = st.tokens[st.pcur].sentence_id
    unread_whole = {}
    for t in st.tokens:
        unread_whole.setdefault(t.sentence_id, True)
        if t.status != "unattempted":
            unread_whole[t.sentence_id] = False
    for x in range(lo, hi):
        s = st.tokens[x].sentence_id
        if s > cur:
            out[x - lo] += C_SKIP_SENT * sum(1 for q in range(cur, s) if q in unread_whole and unread_whole[q]
                                             and q not in st.completed)
    return out


def _page_entry(st: ReadingState) -> np.ndarray:
    d = np.abs(np.arange(st.n) - st.pcur).astype(np.int64)
    return np.where(d <= 2, d, C_PAGE_ENTRY)


def best_path(st: ReadingState, words: list[str], info: WordInfo | None = None, *, page: bool = False,
              pairs: _Pairs | None = None) -> Path | None:
    """The minimum path of one pass (ADR-0013 rule 3) over the fast window or the whole page."""
    info = info or NullWordInfo()
    pairs = pairs or _pairs(words, st.tokens, info)
    m = len(words)
    if page:
        lo, hi = 0, st.n
        entry = _page_entry(st)
    else:
        lo = max(0, st.ccur - 6, st.sentence_start(st.ccur))
        hi = min(st.n, st.pcur + math.ceil(1.5 * m) + 8)
        if hi <= lo:
            return None
        entry = _fast_entry(st, lo, hi)
    return _DP(st, words, pairs, lo, hi, page, st.pcur, entry).best()


# ---------------------------------------------------------------- acceptance (rule 4)


def _runs(st: ReadingState, ops: list[Op]) -> list[list[int]]:
    runs: list[list[int]] = []
    cur: list[int] = []
    for o in ops:
        if o.op in ("align", "join") and o.cls in MATCHED:
            if cur and o.index > cur[-1]:
                cur.append(o.index)
            else:
                if cur:
                    runs.append(cur)
                cur = [o.index]
        elif o.op == "delete" and st.tokens[o.index].function_word and cur:
            continue
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    # a run is consecutive in index once deleted function words are allowed between members
    out = []
    for r in runs:
        piece = [r[0]]
        for x in r[1:]:
            between = range(piece[-1] + 1, x)
            if all(st.tokens[b].function_word for b in between):
                piece.append(x)
            else:
                out.append(piece)
                piece = [x]
        out.append(piece)
    return out


def _accepted(st: ReadingState, path: Path, words: list[str], confs: list[float | None], page: bool,
              info: WordInfo, names: frozenset[str]) -> bool:
    m = len(words)
    if m >= 3 and path.internal > CEILING_PER_WORD * m:
        return False
    content = lambda i: not st.tokens[i].function_word  # noqa: E731
    for r in _runs(st, path.ops):
        if page:
            if (len(r) >= 3 and any(content(i) for i in r)) or \
                    any(content(a) and content(b) for a, b in zip(r, r[1:], strict=False)):
                return True
        elif len(r) >= 2 and any(content(i) for i in r):
            return True
    if page:
        return False
    matched = [o for o in path.ops if o.op in ("align", "join") and o.cls in MATCHED]
    matched_words = sum(o.k for o in matched)
    if len(matched) >= 2 and any(content(o.index) for o in matched) and matched_words >= math.ceil(ANCHOR_MATCH_SHARE * m):
        return True
    if m <= LONE_ANCHOR_MAX_M and len(matched) == 1:
        o = matched[0]
        typed = all(c is None for c in confs)
        if st.pcur - 2 <= o.index <= st.pcur + 2 and (content(o.index) or typed):
            return True
    aligned = [o for o in path.ops if o.op in ("align", "join")]
    if m == 1 and len(aligned) == 1 and aligned[0].cls in (SUBSTITUTE, INFLECTION) and aligned[0].index == st.pcur:
        o, w, conf = aligned[0], words[0], confs[0]
        tok = st.tokens[o.index]
        if content(o.index) and info.is_word(w) and w not in INTERJECTIONS and w not in names and \
                (conf is None or conf >= ANCHOR_CONF) and (sim(w, tok.norm) >= 0.5 or w[:1] == tok.norm[:1]):
            return True
    return False


# ---------------------------------------------------------------- align


def _heard(words, confs) -> tuple[list[str], list[float | None]]:
    out_w, out_c = [], []
    confs = confs if confs is not None else [None] * len(words)
    for w, c in zip(words, confs, strict=True):
        x = norm(w)
        if x:
            out_w.append(x)
            out_c.append(c)
    return out_w, out_c


def align(state: ReadingState, words: list[str], seq: int, info: WordInfo | None = None, *,
          confs: list[float | None] | None = None, inflections: str = "observe",
          names: frozenset[str] = frozenset()):
    """ADR-0013 `align(state, utterance, info) -> (state', observations, events)`; pure and deterministic.

    `words` are the utterance's words (normalised here) with `confs` (None = typed, confident); `seq` numbers
    the utterances of this page read so the self-correction predicate ("the utterance immediately after") is
    exact; `names` are the household's names, never read as a lone misreading (rule 4(d)).
    """
    info = info or NullWordInfo()
    st = copy.deepcopy(state)
    w, c = _heard(words, confs)
    m, _n = len(w), st.n
    info.prepare(set(w) | {t.norm for t in st.tokens})
    pairs = _pairs(w, st.tokens, info)
    path_f = best_path(st, w, info, pairs=pairs) if m else None
    acc_f = path_f is not None and _accepted(st, path_f, w, c, False, info, names)
    path = path_f if acc_f else None
    if m >= 2 and (not acc_f or path_f.cost > TRIGGER_PER_WORD * m):
        path_p = best_path(st, w, info, page=True, pairs=pairs)
        if path_p is not None and _accepted(st, path_p, w, c, True, info, names) and \
                (not acc_f or path_p.cost + PAGE_MARGIN < path_f.cost):
            path = path_p
    if path is None:
        st.unaligned_run += 1
        st.unaligned_words += m
        events: list[Event] = [Unaligned(m)]
        if st.unaligned_run >= UNALIGNED_PROMPT_RUN and st.unaligned_words >= UNALIGNED_PROMPT_WORDS \
                and not st.prompted:
            st.prompted = True
            events.append(FirstWordsPrompt())
        return st, [Observation("unaligned", None, None, word_count=m)], events
    return _apply(st, path, w, c, seq, pairs, inflections)


def _apply(st: ReadingState, path: Path, w: list[str], c: list[float | None], seq: int, pairs: _Pairs,
           inflections: str):
    ops, _n = path.ops, st.n
    observations: list[Observation] = []
    events: list[Event] = []
    aligned = [o for o in ops if o.op in ("align", "join")]
    first, last = aligned[0].index, aligned[-1].index

    # rule 6: entry beyond the frontier
    if first > st.pcur:
        sf = st.tokens[first].sentence_id
        for i in range(st.pcur, first):
            if st.tokens[i].sentence_id == sf and st.tokens[i].status == "unattempted":
                st.tokens[i].status = "unread"

    # rule 5: deletion runs, insertion runs, marks
    skipped: set[int] = set()
    k = 0
    while k < len(ops):
        if ops[k].op == "delete":
            e = k
            while e + 1 < len(ops) and ops[e + 1].op == "delete":
                e += 1
            idx = [ops[x].index for x in range(k, e + 1)]
            if len(idx) >= LINE_SKIP_MIN:
                skipped.update(idx)
                events.append(LineSkipped(len(idx), idx[0], idx[-1] + 1))
            k = e + 1
        else:
            k += 1
    later_matched: dict[int, int] = {}  # token → path position of its last match
    for pos, o in enumerate(ops):
        if o.op in ("align", "join") and o.cls in MATCHED:
            later_matched[o.index] = pos
    seen_matched: set[int] = set()
    sc_marked: set[int] = set()  # path positions of substitutions marked as self-corrections
    for pos, o in enumerate(ops):
        if o.op == "align" and o.cls in (SUBSTITUTE, INFLECTION) and later_matched.get(o.index, -1) > pos:
            sc_marked.add(pos)
    pos = 0
    while pos < len(ops):
        o = ops[pos]
        if o.op == "insert":
            e = pos
            while e + 1 < len(ops) and ops[e + 1].op == "insert":
                e += 1
            run = ops[pos:e + 1]
            if len(run) >= 3:
                observations.append(Observation("unaligned", None, None, word_count=len(run)))
            else:
                nxt = ops[e + 1] if e + 1 < len(ops) else None
                for q, ins in enumerate(run):
                    mark = False
                    if q == len(run) - 1 and nxt is not None and nxt.op in ("align", "join") and nxt.cls in MATCHED:
                        tk = st.tokens[nxt.index].norm
                        hw = w[ins.word]
                        mark = sim(hw, tk) >= 0.5 or hw[:1] == tk[:1]
                    observations.append(Observation("inserted", ins.index, ins.index, w[ins.word],
                                                    self_correction=mark))
            pos = e + 1
            continue
        if o.op == "jump":
            pos += 1
            continue
        tok = st.tokens[o.index]
        completed = tok.sentence_id in st.completed
        if o.op in ("align", "join") and o.cls in MATCHED:
            heard = " ".join(w[o.word:o.word + o.k])
            s = float(pairs.sim[o.word, o.index]) / 100 if o.k == 1 else 1.0
            observations.append(Observation("matched", o.index, o.index + 1, heard, s, o.cls, tok.function_word,
                                            repeat=o.index in seen_matched))
            seen_matched.add(o.index)
            if tok.status in ("unattempted", "provisional", "unread"):
                tok.status = "committed" if completed else "provisional"
            elif tok.status == "candidate" and not tok.supplied:
                tok.status = "settled"
                reason = "self_corrected" if tok.created_by is not None and seq == tok.created_by + 1 else "reread"
                events.append(CandidateWithdrawn(o.index, reason))
        elif o.op == "align" or (o.op == "delete" and o.index not in skipped):
            heard = w[o.word] if o.op == "align" else None
            kind = "substituted" if o.op == "align" else "deleted"
            s = float(pairs.sim[o.word, o.index]) / 100 if o.op == "align" else None
            mark = pos in sc_marked
            observations.append(Observation(kind, o.index, o.index + 1, heard, s, o.cls if o.op == "align" else None,
                                            tok.function_word, self_correction=mark))
            if tok.status in ("unattempted", "provisional", "unread"):
                observed = tok.function_word or mark or \
                    (o.cls == INFLECTION and inflections == "observe") or \
                    (o.op == "align" and c[o.word] is not None and c[o.word] < LOW_CONF)
                if observed:
                    tok.status = "committed" if completed else "provisional"
                else:
                    tok.status = "candidate"
                    tok.created_by = seq
                    events.append(CandidateCreated(o.index, tok.text, heard, len(observations) - 1,
                                                   "substitution" if o.op == "align" else "deletion"))
        elif o.op == "delete":  # part of a skipped line
            if tok.status in ("unattempted", "provisional"):
                tok.status = "unread"
        pos += 1

    # rule 8
    st.pcur = max(st.pcur, last + 1)
    st.unaligned_run, st.unaligned_words, st.prompted = 0, 0, False
    # rule 9
    while st.ccur < st.pcur and st.tokens[st.ccur].status in ("provisional", "committed", "candidate", "settled"):
        st.ccur += 1
    # rule 10
    for sid in st.sentence_ids():
        if sid not in st.completed and st.last_index(sid) < st.pcur:
            events.append(SentenceReached(sid))
    return st, observations, events


# ---------------------------------------------------------------- supplying a word


def supply(state: ReadingState, i: int, seq: int) -> tuple[ReadingState, list[Event]]:
    """ADR-0013 → Supplying a word: Leafi said token i after an accepted hint."""
    st = copy.deepcopy(state)
    tok = st.tokens[i]
    events: list[Event] = []
    if tok.status == "candidate":
        tok.supplied = True
        events.append(OriginSupplied(i))
    elif tok.status in ("unattempted", "provisional", "unread"):
        tok.status, tok.supplied, tok.created_by = "candidate", True, seq
        events.append(CandidateCreated(i, tok.text, None, None, "supplied"))
    st.pcur = max(st.pcur, i + 1)
    while st.ccur < st.pcur and st.tokens[st.ccur].status in ("provisional", "committed", "candidate", "settled"):
        st.ccur += 1
    for sid in st.sentence_ids():
        if sid not in st.completed and st.last_index(sid) < st.pcur:
            events.append(SentenceReached(sid))
    return st, events


# ---------------------------------------------------------------- session rules on the state (ADR-0013)


def complete_sentence(state: ReadingState, sid: int) -> tuple[ReadingState, list[int]]:
    """Sentence completion. Returns (state', candidate token indexes of the sentence in position order)."""
    st = copy.deepcopy(state)
    first, last = st.first_index(sid), st.last_index(sid)
    cands = []
    for i in range(first, last + 1):
        t = st.tokens[i]
        if t.status == "provisional":
            t.status = "committed"
        elif t.status == "unattempted":
            t.status = "unread"
        elif t.status == "candidate":
            cands.append(i)
    st.ccur = max(st.ccur, last + 1)
    st.pcur = max(st.pcur, st.ccur)
    st.completed.add(sid)
    st.turn_id += 1
    return st, cands


def pause_completes(state: ReadingState) -> int | None:
    """Completion (ii): the current sentence when `pcur` is within its last two token indexes or beyond and
    no content-word token of it is still unattempted (a slow reader's pause does not end the sentence)."""
    sid = state.current_sentence()
    if sid is None or sid in state.completed:
        return None
    first, last = state.first_index(sid), state.last_index(sid)
    if state.pcur < last - 1:
        return None
    if any(t.status == "unattempted" and not t.function_word for t in state.tokens[first:last + 1]):
        return None
    return sid


def settle(state: ReadingState, indexes: list[int]) -> ReadingState:
    st = copy.deepcopy(state)
    for i in indexes:
        if st.tokens[i].status == "candidate":
            st.tokens[i].status = "settled"
    return st


def open_candidates(state: ReadingState) -> list[int]:
    return [i for i, t in enumerate(state.tokens) if t.status == "candidate"]


def back(state: ReadingState, n: int = 1) -> ReadingState:
    """`/back N`: reopen `cur` and N−1 before it; `cur` = the sentence containing `pcur − 1` when `pcur` is at a
    sentence start or at `n`, else the sentence containing `pcur` (ADR-0013 → `/back N`)."""
    st = copy.deepcopy(state)
    if st.n == 0:
        return st
    ids = st.sentence_ids()
    at_boundary = st.pcur >= st.n or (st.pcur > 0 and st.sentence_start(st.pcur) == st.pcur)
    cur = st.tokens[st.pcur - 1].sentence_id if at_boundary and st.pcur > 0 else st.tokens[st.pcur].sentence_id
    pos = ids.index(cur)
    target = ids[max(0, pos - (max(1, n) - 1))]
    for sid in ids[ids.index(target): pos + 1]:
        st.completed.discard(sid)
        for i in range(st.first_index(sid), st.last_index(sid) + 1):
            if st.tokens[i].status in ("committed", "provisional", "unread"):
                st.tokens[i].status = "unattempted"
    st.pcur = st.ccur = st.first_index(target)
    st.turn_id += 1
    return st


def skip_read(state: ReadingState) -> tuple[ReadingState, int | None, list[int]]:
    """`skip` in READ: complete the current sentence by (iii) and move both cursors to the next sentence."""
    sid = state.current_sentence()
    if sid is None:
        return state, None, []
    st, cands = complete_sentence(state, sid)
    nxt = st.last_index(sid) + 1
    st.pcur = st.ccur = nxt
    return st, sid, cands


def opened(fresh: ReadingState, c: int | None, touched: set[int] = frozenset(),
           range_from: int | None = None) -> ReadingState:
    """The pure part of ADR-0013 → Opening a page read: `fresh` is the page at its current revision, `c` the
    learner's previous `ccur` already mapped to it (None: no previous page read), `touched` the token indexes a
    correction since then touched. `range_from` set → a `{from, to}` or familiar read starting there."""
    st = copy.deepcopy(fresh)
    for t in st.tokens:
        t.status, t.created_by, t.miscue_id, t.supplied = "unattempted", None, None, False
    st.completed = set()
    st.unaligned_run, st.unaligned_words, st.prompted = 0, 0, False
    if range_from is not None or c is None:
        st.pcur = st.ccur = range_from or 0
        return st
    if c < st.n:
        c = st.sentence_start(c)
    for i in range(c):
        st.tokens[i].status = "unread" if i in touched else "committed"
    st.completed = {sid for sid in st.sentence_ids() if st.last_index(sid) < c}
    st.pcur = st.ccur = c
    return st


def resumed(state: ReadingState) -> ReadingState:
    """"Continue from page N?": `opened` with range `rest` from this page read's `ccur` (same revision)."""
    return opened(state, state.ccur)


# ---------------------------------------------------------------- practice retry (ADR-0013 → Practice)


def retry_result(heard: list[str], target: str, info: WordInfo | None = None,
                 confs: list[float | None] | None = None) -> Literal["pass", "fail", "unclear"]:
    """One attempt: `pass` when some heard word is the target by `exact` or `phones`, or a run of heard number
    words is it by `number join`, confidently; `fail` when every word is confident and none passes."""
    info = info or NullWordInfo()
    w, c = _heard(heard, confs)
    if not w:
        return "unclear"
    tok = Tok(target, norm(target), 0, len(target), 1)
    info.prepare(set(w) | {tok.norm})
    ok = lambda x: x is None or x >= RETRY_MIN_CONF  # noqa: E731
    readings = numeral_readings(target)
    for j, x in enumerate(w):
        if pair_class(x, tok, info) in (EXACT, PHONES) and ok(c[j]):
            return "pass"
    for k in range(2, MAX_JOIN + 1):
        for j in range(len(w) - k + 1):
            key = _join_key(w, j, k)
            if key is not None and key in readings and all(ok(x) for x in c[j:j + k]):
                return "pass"
    return "fail" if all(ok(x) for x in c) else "unclear"


def retry_matches(retry_words: list[str], expected: str) -> bool:
    """v1 call sites (the v1 session's PRACTICE): a v2 `pass` on a typed or confident retry."""
    return retry_result(retry_words, expected) == "pass"
