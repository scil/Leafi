"""Reading alignment and the pure reading-state rules. ADR-0013 is the only owner of these rules; this module
implements its pseudocode and must not add rules of its own (implementation choices are in the plan's
Decision log).

Costs are integers in tenths (ADR-0013 × 10) so ties are exact: match 0, fuzzy 3, substitute 10,
delete 8, insert 12, jump 1 per token, boundary 5.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Literal

from leafi.core.text import TextToken, norm, sim, tokenize

Status = Literal["unattempted", "provisional", "committed", "candidate", "settled", "unread"]

C_MATCH, C_FUZZY, C_SUB, C_DEL, C_INS, C_JUMP, C_BOUND = 0, 3, 10, 8, 12, 1, 5
# Operation order for the final lexicographic tie-break over (expected index, operation).
OP_MATCH, OP_FUZZY, OP_SUB, OP_DEL, OP_INS = 0, 1, 2, 3, 4
FUZZY_SIM = 0.80
LINE_SKIP_MIN = 4  # an internal run of deleted tokens longer than 3


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

    # ---- construction / persistence
    @classmethod
    def from_text(cls, text: str, **kw) -> ReadingState:
        return cls.from_tokens(tokenize(text), **kw)

    @classmethod
    def from_tokens(cls, toks: list[TextToken], **kw) -> ReadingState:
        return cls([Tok(t.text, t.norm, t.start, t.end, t.sentence_id) for t in toks], **kw)

    def to_json(self) -> dict:
        return {
            "status": [t.status for t in self.tokens],
            "created_by": [t.created_by for t in self.tokens],
            "pcur": self.pcur, "ccur": self.ccur, "completed": sorted(self.completed),
            "turn_id": self.turn_id, "page_read_id": self.page_read_id, "revision_id": self.revision_id,
        }

    @classmethod
    def from_json(cls, text: str, data: dict) -> ReadingState:
        st = cls.from_text(text, page_read_id=data.get("page_read_id"), revision_id=data.get("revision_id"))
        for t, s, c in zip(st.tokens, data["status"], data["created_by"], strict=True):
            t.status, t.created_by = s, c
        st.pcur, st.ccur = data["pcur"], data["ccur"]
        st.completed = set(data["completed"])
        st.turn_id = data["turn_id"]
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
    kind: Literal["matched", "substituted", "deleted", "inserted"]
    token_start: int
    token_end: int
    heard: str | None = None
    sim: float | None = None


@dataclass(frozen=True)
class SentenceReached:
    sentence_id: int


@dataclass(frozen=True)
class Unanchored:
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
    observation_index: int


@dataclass(frozen=True)
class CandidateWithdrawn:
    token_index: int
    reason: Literal["self_corrected", "reread"]


Event = SentenceReached | Unanchored | LineSkipped | CandidateCreated | CandidateWithdrawn


# ---------------------------------------------------------------- alignment


@dataclass
class _Op:
    op: int  # OP_*
    index: int  # expected index (insertions: anchor = next expected index)
    word: int | None  # heard word index
    sim: float | None = None


def _opcost(tok: Tok, w: str) -> tuple[int, int, float]:
    if w == tok.norm:
        return C_MATCH, OP_MATCH, 1.0
    s = sim(w, tok.norm)
    if s >= FUZZY_SIM:
        return C_FUZZY, OP_FUZZY, s
    return C_SUB, OP_SUB, s


def best_path(tokens: list[Tok], lo: int, hi: int, words: list[str], pcur: int) -> list[_Op] | None:
    """Minimum-cost path under ADR-0013 step 2 with the unique tie-break. None = no aligned token."""
    m = len(words)
    if m == 0 or hi <= lo:
        return None
    sent = [t.sentence_id for t in tokens]
    cache: dict[tuple[int, int], tuple[int, int, float]] = {}

    def oc(i: int, j: int) -> tuple[int, int, float]:
        k = (i, j)
        if k not in cache:
            cache[k] = _opcost(tokens[i], words[j])
        return cache[k]

    inf = (math.inf, math.inf)
    # V[(i, j, c)] = best (cost, insertions) from state "next token i, next word j, aligned count c in sent(i-1)"
    V: dict[tuple[int, int, int], tuple[float, float]] = {}

    def trans(i: int, j: int, c: int):
        """Transitions in lexicographic (index, op) order; END (shortest sequence) first."""
        out = []
        if j == m:
            out.append(("end", None, (C_BOUND if c == 1 else 0, 0), None))
        if i < hi:
            cross = sent[i] != sent[i - 1]
            pen = C_BOUND if (cross and c == 1) else 0
            cbase = 0 if cross else c
            if j < m:
                cost, op, s = oc(i, j)
                out.append(("align", (i + 1, j + 1, min(cbase + 1, 2)), (cost + pen, 0), _Op(op, i, j, s)))
            out.append(("del", (i + 1, j, cbase), (C_DEL + pen, 0), _Op(OP_DEL, i, None)))
        if j < m:
            out.append(("ins", (i, j + 1, c), (C_INS, 1), _Op(OP_INS, i, j)))
        out.sort(key=lambda t: (-1, 0) if t[0] == "end" else (t[3].index, t[3].op))
        return out

    for i in range(hi, lo, -1):
        for j in range(m, -1, -1):
            for c in (0, 1, 2):
                best = inf
                for _, nxt, step, _op in trans(i, j, c):
                    sub = (0, 0) if nxt is None else V[nxt]
                    val = (sub[0] + step[0], sub[1] + step[1])
                    if val < best:
                        best = val
                V[(i, j, c)] = best

    def rebuild(i: int, j: int, c: int) -> list[_Op]:
        ops: list[_Op] = []
        while True:
            target = V[(i, j, c)]
            for kind, nxt, step, op in trans(i, j, c):
                sub = (0, 0) if nxt is None else V[nxt]
                if (sub[0] + step[0], sub[1] + step[1]) == target:
                    if kind == "end":
                        return ops
                    ops.append(op)
                    i, j, c = nxt
                    break

    candidates = []
    for f in range(lo, hi):
        for j0 in range(m):
            cost, op, s = oc(f, j0)
            sub = V[(f + 1, j0 + 1, 1)]
            total = C_INS * j0 + C_JUMP * abs(f - pcur) + cost + sub[0]
            candidates.append(((total, abs(f - pcur), j0 + sub[1]), f, j0, op, s))
    candidates.sort(key=lambda t: t[0])
    best_key = candidates[0][0]
    if (C_INS * m, math.inf, m) < best_key:  # inserting everything is strictly cheaper: nothing aligned
        return None
    tied = []
    for key, f, j0, op, s in candidates:
        if key != best_key:
            break
        path = [_Op(OP_INS, f, j) for j in range(j0)] + [_Op(op, f, j0, s)] + rebuild(f + 1, j0 + 1, 1)
        tied.append(path)
    return min(tied, key=lambda p: [(o.index, o.op) for o in p])


def _accepted(path: list[_Op], pcur: int, min_run: int, allow_singleton: bool) -> bool:
    run = best = 0
    prev: _Op | None = None
    matches = []
    for o in path:
        if o.op in (OP_MATCH, OP_FUZZY):
            matches.append(o)
            adjacent = prev is not None and prev.op in (OP_MATCH, OP_FUZZY) and prev.index == o.index - 1
            run = run + 1 if adjacent else 1
        else:
            run = 0
        best = max(best, run)
        prev = o
    if best >= min_run:
        return True
    return allow_singleton and len(matches) == 1 and pcur - 2 <= matches[0].index <= pcur + 2


def align(state: ReadingState, words: list[str], seq: int, *, whole_page: bool = False):
    """ADR-0013 `align(state, utterance) -> (state', observations, events)`; pure and deterministic.

    `words` are the utterance's words (normalised here); `seq` numbers the utterances of this page read so
    the self-correction predicate ("the utterance immediately after") is exact. `whole_page=True` is the
    Reposition variant: lo = 0, hi = n, run ≥ 3, and the cursors move to the first aligned index.
    """
    st = copy.deepcopy(state)
    w = [norm(x) for x in words]
    w = [x for x in w if x]
    m, n = len(w), st.n
    if whole_page:
        lo, hi = 0, n
    else:
        lo = max(0, st.ccur - 6, st.sentence_start(st.ccur))
        hi = min(n, st.pcur + math.ceil(1.5 * m) + 8)
    path = best_path(st.tokens, lo, hi, w, st.pcur)
    if path is None or not _accepted(path, st.pcur, 3 if whole_page else 2, not whole_page):
        return state, [], [Unanchored()]

    aligned = [o for o in path if o.op in (OP_MATCH, OP_FUZZY, OP_SUB)]
    first, last = aligned[0].index, aligned[-1].index
    if whole_page:
        for i in range(st.ccur, first):
            if st.tokens[i].status in ("unattempted", "provisional"):
                st.tokens[i].status = "unread"
        st.ccur = st.pcur = first

    # step 4 — observations; internal delete runs longer than 3 become line_skipped
    observations: list[Observation] = []
    events: list[Event] = []
    skipped: set[int] = set()
    k = 0
    while k < len(path):
        if path[k].op == OP_DEL:
            run_end = k
            while run_end + 1 < len(path) and path[run_end + 1].op == OP_DEL:
                run_end += 1
            idx = [path[x].index for x in range(k, run_end + 1)]
            if len(idx) >= LINE_SKIP_MIN:
                skipped.update(idx)
                events.append(LineSkipped(len(idx), idx[0], idx[-1] + 1))
            k = run_end + 1
        else:
            k += 1

    # step 5 — status updates in path order
    for o in path:
        tok = st.tokens[o.index] if o.index < n else None
        if o.op == OP_INS:
            observations.append(Observation("inserted", o.index, o.index, w[o.word], None))
            continue
        assert tok is not None
        if o.op in (OP_MATCH, OP_FUZZY):
            observations.append(Observation("matched", o.index, o.index + 1, w[o.word], o.sim))
            if tok.status in ("unattempted", "provisional", "unread"):
                tok.status = "provisional"
            elif tok.status == "candidate":
                tok.status = "settled"
                reason = "self_corrected" if tok.created_by is not None and seq == tok.created_by + 1 else "reread"
                events.append(CandidateWithdrawn(o.index, reason))
        elif o.op == OP_SUB or (o.op == OP_DEL and o.index not in skipped):
            heard = w[o.word] if o.op == OP_SUB else None
            kind = "substituted" if o.op == OP_SUB else "deleted"
            observations.append(Observation(kind, o.index, o.index + 1, heard, o.sim))
            if tok.status in ("unattempted", "provisional", "unread"):
                tok.status = "candidate"
                tok.created_by = seq
                events.append(CandidateCreated(o.index, tok.text, heard, len(observations) - 1))
        elif o.op == OP_DEL:  # part of a skipped line
            if tok.status in ("unattempted", "provisional"):
                tok.status = "unread"
    st.pcur = max(st.pcur, last + 1)

    # step 6 — commit scan
    while st.ccur < st.pcur and st.tokens[st.ccur].status in ("provisional", "committed", "candidate", "settled"):
        st.ccur += 1

    # step 7 — sentence_reached once per sentence
    for sid in st.sentence_ids():
        if sid not in st.completed and st.last_index(sid) < st.pcur:
            events.append(SentenceReached(sid))
    return st, observations, events


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
    """Completion (ii): the current sentence when `pcur` is within its last two token indexes or beyond."""
    sid = state.current_sentence()
    if sid is None or sid in state.completed:
        return None
    return sid if state.pcur >= state.last_index(sid) - 1 else None


def settle(state: ReadingState, indexes: list[int]) -> ReadingState:
    st = copy.deepcopy(state)
    for i in indexes:
        if st.tokens[i].status == "candidate":
            st.tokens[i].status = "settled"
    return st


def open_candidates(state: ReadingState) -> list[int]:
    return [i for i, t in enumerate(state.tokens) if t.status == "candidate"]


def back(state: ReadingState, n: int = 1) -> ReadingState:
    """`/back N`: reopen the current sentence and N−1 before it."""
    st = copy.deepcopy(state)
    if st.n == 0:
        return st
    ids = st.sentence_ids()
    cur = st.current_sentence() if st.pcur < st.n else ids[-1]
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


def resumed(state: ReadingState) -> ReadingState:
    """Interrupted-session resume: cursors at the old `ccur`, tokens before it committed, the rest unattempted."""
    st = copy.deepcopy(state)
    c = st.ccur
    for i, t in enumerate(st.tokens):
        t.status = "committed" if i < c else "unattempted"
        t.created_by = None
    st.pcur = st.ccur = c
    st.completed = {sid for sid in st.sentence_ids() if st.last_index(sid) < c}
    return st


def retry_matches(retry_words: list[str], expected: str) -> bool:
    """Practice retry test: `norm(retry) == norm(expected)` or `sim ≥ 0.80` on the whole retry."""
    heard = " ".join(x for x in (norm(w) for w in retry_words) if x)
    target = norm(expected)
    return heard == target or sim(heard, target) >= FUZZY_SIM
