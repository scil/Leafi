"""ADR-0013 v2 rule 3 against a brute-force enumeration of every path (plan M4; never mocked).

The reference scores each path from the ADR's costs and tie-break order alone (cost, distance of the first
aligned token from `pcur`, insertions, back jumps, then the lexicographic order of operations) and the DP
must return exactly the same path, in both pass bounds.
"""

from __future__ import annotations

import math
import random

from leafi.core.text import norm, numeral_readings
from leafi.core.wordinfo import TableWordInfo
from leafi.study.alignment import (
    _COST,
    C_BOUND,
    C_DEL0,
    C_DELX,
    C_INS,
    C_JUMP0,
    C_PAGE_ENTRY,
    C_SKIP_SENT,
    JOIN,
    MAX_JOIN,
    RANK,
    ReadingState,
    _join_key,
    best_path,
    pair_class,
)

VOCAB = ["the", "a", "dog", "cat", "sat", "ran", "on", "mat", "big", "red", "21", "two"]
HEARD = ["the", "a", "dog", "cat", "sat", "ran", "on", "mat", "big", "red", "dgo", "cta", "twenty", "one",
         "two", "bag"]
INFO = TableWordInfo(words=["the", "a", "dog", "cat", "sat", "ran", "on", "mat", "big", "red", "bag", "twenty",
                            "one", "two"],
                     phones={"two": {"tu"}, "to": {"tu"}},
                     lemmas={"ran": {"run"}, "sat": {"sit"}})


def _window(st: ReadingState, m: int, page: bool) -> tuple[int, int]:
    if page:
        return 0, st.n
    return max(0, st.ccur - 6, st.sentence_start(st.ccur)), min(st.n, st.pcur + math.ceil(1.5 * m) + 8)


def _entry(st: ReadingState, f: int, page: bool) -> int:
    d = abs(f - st.pcur)
    if page:
        return d if d <= 2 else C_PAGE_ENTRY
    if st.pcur >= st.n:
        return d
    cur, sf = st.tokens[st.pcur].sentence_id, st.tokens[f].sentence_id
    pen = 0
    for q in range(cur, sf):
        toks = [t for t in st.tokens if t.sentence_id == q]
        if toks and all(t.status == "unattempted" for t in toks) and q not in st.completed:
            pen += C_SKIP_SENT
    return d + pen


def reference(st: ReadingState, words: list[str], page: bool):
    m = len(words)
    lo, hi = _window(st, m, page)
    if hi <= lo:
        return None
    toks = st.tokens
    slen: dict[int, int] = {}
    for t in toks:
        slen[t.sentence_id] = slen.get(t.sentence_id, 0) + 1
    sstart = {sid: st.first_index(sid) for sid in slen}

    def charge(c, t):
        return C_BOUND if c == 1 and slen[toks[t].sentence_id] >= 2 else 0

    def arrivals(j, u):
        out = [(1, _COST[pair_class(words[j], toks[u], INFO)], RANK[pair_class(words[j], toks[u], INFO)])]
        for k in range(2, MAX_JOIN + 1):
            key = _join_key(words, j, k)
            if j + k <= m and key is not None and key in numeral_readings(toks[u].text):
                out.append((k, 0, RANK[JOIN]))
        return out

    best = []

    def go(j, t, c, flag_a, cost, ins, jumps, ops, first):
        if j == m:
            best.append(((cost + charge(c, t), abs(first - st.pcur), ins, jumps, ops), ops))
            return
        go(j + 1, t, c, False, cost + C_INS, ins + 1, jumps, ops + [(t + 1, RANK["insert"], 0)], first)
        for u in range(t + 1, hi):
            d = 0 if u == t + 1 else C_DEL0 + C_DELX * (u - t - 2)
            dels = [(x, RANK["delete"], 0) for x in range(t + 1, u)]
            same = toks[u].sentence_id == toks[t].sentence_id
            for k, pc, rank in arrivals(j, u):
                c2, pre = (min(c + 1, 2), 0) if same else (1, charge(c, t))
                go(j + k, u, c2, True, cost + pre + d + pc, ins, jumps, ops + dels + [(u, rank, k)], first)
        if flag_a:
            sid = toks[t].sentence_id
            lowb = sstart[sid]
            if not page and sid - 1 in sstart:
                lowb = sstart[sid - 1]
            for kk in range(max(lo, lowb), t + 1):
                same = toks[kk].sentence_id == toks[t].sentence_id
                for k, pc, rank in arrivals(j, kk):
                    c2, pre = (min(c + 1, 2), 0) if same else (1, charge(c, t))
                    go(j + k, kk, c2, True, cost + pre + C_JUMP0 + (t - kk) + pc, ins, jumps + 1,
                       ops + [(kk, RANK["jump"], 0), (kk, rank, k)], first)

    for j0 in range(m):
        for f in range(lo, hi):
            for k, pc, rank in arrivals(j0, f):
                lead = [(f, RANK["insert"], 0)] * j0
                go(j0 + k, f, 1, True, C_INS * j0 + _entry(st, f, page) + pc, j0, 0, lead + [(f, rank, k)], f)
    if not best:
        return None
    return min(best)[1]


def _as_tuples(path) -> list[tuple[int, int, int]]:
    out = []
    for o in path.ops:
        if o.op == "insert":
            out.append((o.index, RANK["insert"], 0))
        elif o.op == "delete":
            out.append((o.index, RANK["delete"], 0))
        elif o.op == "jump":
            out.append((o.index, RANK["jump"], 0))
        else:
            out.append((o.index, RANK[o.cls], o.k))
    return out


def _case(rng: random.Random):
    n = rng.randint(1, 6)
    toks = [rng.choice(VOCAB) for _ in range(n)]
    text, out = "", []
    for i, w in enumerate(toks):
        out.append(w)
        if i < n - 1 and rng.random() < 0.3:
            out[-1] += "."
    text = " ".join(out) + "."
    st = ReadingState.from_text(text)
    st.pcur = st.ccur = rng.randint(0, st.n)
    for i in range(st.pcur):
        st.tokens[i].status = "provisional"
    words = [norm(rng.choice(HEARD)) for _ in range(rng.randint(1, 4))]
    return st, words


def _reading_case(rng: random.Random):
    """Utterances made from the page itself with drops, swaps and spoken numerals, so deletions and joins
    occur often."""
    st, _ = _case(rng)
    while st.n < 4:
        st, _ = _case(rng)
    st.pcur = st.ccur = rng.randint(0, max(0, st.n - 3))
    for t in st.tokens:
        t.status = "unattempted"
    for i in range(st.pcur):
        st.tokens[i].status = "provisional"
    words = []
    for t in st.tokens[st.pcur:]:
        r = rng.random()
        if r < 0.25:
            continue
        if t.text == "21":
            words += ["twenty", "one"]
        elif r < 0.4:
            words.append(rng.choice(HEARD))
        else:
            words.append(t.norm)
        if len(words) >= 4:
            break
    return st, [norm(w) for w in words[:4]] or ["dog"]


def test_dp_equals_brute_force_on_reading_like_cases():
    rng = random.Random(7)
    seen = set()
    for _ in range(500):
        st, words = _reading_case(rng)
        for page in (False, True):
            ref = reference(st, words, page)
            got = best_path(st, words, INFO, page=page)
            assert (got is None) == (ref is None)
            if got is not None:
                assert _as_tuples(got) == ref, ([t.text for t in st.tokens], st.pcur, words, page)
                seen.update(o.op for o in got.ops)
    assert {"delete", "join", "jump", "insert", "align"} <= seen


def test_dp_equals_brute_force_on_random_small_cases():
    rng = random.Random(20261022)
    checked = 0
    for _ in range(600):
        st, words = _case(rng)
        for page in (False, True):
            ref = reference(st, words, page)
            got = best_path(st, words, INFO, page=page)
            if ref is None:
                assert got is None
                continue
            assert got is not None
            assert _as_tuples(got) == ref, (st.statuses(), [t.text for t in st.tokens], words, page)
            checked += 1
    assert checked > 800
