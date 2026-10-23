"""Plan M0.4: timed prototype of the ADR-0013 v2 alignment DP (cost only, page pass shape).

Checks a numpy implementation, vectorised over tokens and looped over heard words, against a brute-force
enumeration of every path on small inputs, then times it on a 400-token page with 25 heard words.

Covered: pair costs (exact 0 / fuzzy 3 / substitute 10 via rapidfuzz cdist), affine deletions 8 + 3(L-1),
insert 12, back jumps 4 + (a-k) only directly after an aligned token (page-pass bound: same sentence; fast-pass
bound: also the previous sentence), entry cost (page form), boundary 5 per visit with fewer than min(2, len(s))
aligned tokens. Not covered (do not change the complexity class): `number join`, the phones / inflection classes
(precomputed per word), the tie-break keys (packed into the same int64 arrays), path reconstruction (O(n + m)
with back-pointers). Prototype code: deleted after the decision (plan M0.4).

    .venv\\Scripts\\python scripts/prototypes/dp_v2_proto.py
"""

from __future__ import annotations

import random
import statistics
import sys
import time

import numpy as np
from rapidfuzz import fuzz, process

INF = 10**9
C_FUZZY, C_SUB, C_DEL0, C_DELX, C_INS, C_JUMP0, C_BOUND, C_PAGE_ENTRY = 3, 10, 8, 3, 12, 4, 5, 15


def pair_costs(words: list[str], toks: list[str], is_word) -> np.ndarray:
    sim = process.cdist(words, toks, scorer=fuzz.ratio, dtype=np.int32, workers=1)
    exact = np.array([[w == t for t in toks] for w in words]) if len(words) * len(toks) < 2000 else None
    if exact is None:
        tok_arr = np.array(toks, dtype=object)
        exact = np.stack([tok_arr == w for w in words])
    nonword = np.array([not is_word(w) for w in words])[:, None]
    p = np.where(exact, 0, np.where((sim >= 80) & nonword, C_FUZZY, C_SUB))
    return p.astype(np.int64)


def shift(x: np.ndarray, k: int) -> np.ndarray:
    """x moved right by k positions, INF filled."""
    out = np.full_like(x, INF)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def entry_cost(n: int, pcur: int) -> np.ndarray:
    d = np.abs(np.arange(n) - pcur)
    return np.where(d <= 2, d, C_PAGE_ENTRY).astype(np.int64)


def seg_prefix_min(x: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Inclusive prefix minimum that restarts at every sentence start."""
    out = np.empty_like(x)
    for s0, s1 in zip(starts[:-1], starts[1:], strict=True):
        out[s0:s1] = np.minimum.accumulate(x[s0:s1])
    return out


def seg_suffix_min(x: np.ndarray, starts: np.ndarray) -> np.ndarray:
    out = np.empty_like(x)
    for s0, s1 in zip(starts[:-1], starts[1:], strict=True):
        out[s0:s1] = np.minimum.accumulate(x[s0:s1][::-1])[::-1]
    return out


def dp_vectorised(sid: list[int], p: np.ndarray, pcur: int, fast_back: bool = False) -> int:
    """Minimum path cost. States after word j: A[c][t] last op align at t, I[c][t] last op insert after t;
    c = 1 or 2 aligned tokens (capped) in the open visit."""
    m, n = p.shape
    s = np.asarray(sid)
    starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])
    starts = np.r_[starts, n]
    slen = np.diff(starts)
    tok_len = np.repeat(slen, slen)  # length of each token's sentence
    sstart = np.repeat(starts[:-1], slen)
    idx = np.arange(n, dtype=np.int64)
    charge1 = np.where(tok_len >= 2, C_BOUND, 0).astype(np.int64)  # closing a visit with c = 1
    ent = entry_cost(n, pcur)

    A1 = np.full(n, INF, np.int64)
    A2 = np.full(n, INF, np.int64)
    I1 = np.full(n, INF, np.int64)
    I2 = np.full(n, INF, np.int64)
    ins_prefix = 0  # cost of inserting every word so far with nothing aligned yet
    for j in range(m):
        pj = p[j]
        X1 = np.minimum(A1, I1)  # sources for advance and delete (any last op)
        X2 = np.minimum(A2, I2)
        # closing cost of the visit at t when leaving its sentence
        close = np.minimum(X1 + charge1, X2)
        # --- same-sentence targets go to c = 2; cross-sentence targets go to c = 1
        # advance t = u - 1
        prev_same = np.r_[False, s[1:] == s[:-1]]
        same_adv = np.where(prev_same, shift(np.minimum(X1, X2), 1), INF)
        cross = np.where(~prev_same, shift(close, 1), INF)
        # delete run from t <= u - 2: 3u - 3t + 2
        base_same = np.minimum(X1, X2) - 3 * idx
        pm_same = seg_prefix_min(base_same, starts)
        shifted = shift(pm_same, 2)  # prefix min up to u - 2
        ok_same = (idx - 2) >= sstart
        same_del = np.where(ok_same, shifted + 3 * idx + 2, INF)
        # cross-sentence sources: t < sentence_start(u) and t <= u - 2 (t = u - 1 is the advance case)
        gpm = np.minimum.accumulate(close - 3 * idx)
        lim = np.minimum(sstart - 1, idx - 2)
        cross_del = np.where(lim >= 0, gpm[np.maximum(lim, 0)] + 3 * idx + 2, INF)
        # back jump from an aligned token t >= u (A only), same sentence: 4 + t - u
        bsame = seg_suffix_min(np.minimum(A1, A2) + idx, starts)
        same_jump = bsame - idx + C_JUMP0
        cand2 = np.minimum.reduce([same_adv, same_del, same_jump])
        cand1 = np.minimum(cross, cross_del)
        if fast_back:
            # back jump into the previous sentence from any aligned t in the next sentence
            closeA = np.minimum(A1 + charge1, A2) + idx
            smin = np.array([closeA[a:b].min() if b > a else INF for a, b in zip(starts[:-1], starts[1:], strict=True)])
            nxt = np.r_[smin[1:], INF]
            per_tok = np.repeat(nxt, slen)
            cand1 = np.minimum(cand1, per_tok - idx + C_JUMP0)
        start = ins_prefix + ent  # first aligned word here
        nA1 = np.minimum(cand1, start) + pj
        nA2 = cand2 + pj
        nI1 = np.minimum(A1, I1) + C_INS
        nI2 = np.minimum(A2, I2) + C_INS
        A1, A2, I1, I2 = (np.minimum(x, INF) for x in (nA1, nA2, nI1, nI2))
        ins_prefix += C_INS
    end = np.minimum(np.minimum(A1, I1) + charge1, np.minimum(A2, I2))
    return int(end.min())


def dp_brute(sid: list[int], p: np.ndarray, pcur: int, fast_back: bool = False) -> int:
    """Enumerate every operation sequence with the same rules (reference for small inputs)."""
    m, n = p.shape
    s = sid
    slen = {x: s.count(x) for x in set(s)}
    sstart = {x: s.index(x) for x in set(s)}
    ent = entry_cost(n, pcur)

    def charge(c, t):
        return C_BOUND if c < min(2, slen[s[t]]) else 0

    best = INF

    def go(j, t, c, last_align, cost):
        nonlocal best
        if cost >= best:
            return
        if j == m:
            best = min(best, cost + charge(c, t))
            return
        go(j + 1, t, c, False, cost + C_INS)
        for u in range(t + 1, n):
            L = u - t - 1
            d = 0 if L == 0 else C_DEL0 + C_DELX * (L - 1)
            if s[u] == s[t]:
                go(j + 1, u, min(c + 1, 2), True, cost + d + p[j][u])
            else:
                go(j + 1, u, 1, True, cost + charge(c, t) + d + p[j][u])
        if last_align:
            lo_k = sstart[s[t]]
            if fast_back and s[t] > min(s):
                lo_k = sstart[s[t] - 1]
            for k in range(lo_k, t + 1):
                jc = C_JUMP0 + (t - k)
                if s[k] == s[t]:
                    go(j + 1, k, min(c + 1, 2), True, cost + jc + p[j][k])
                else:
                    go(j + 1, k, 1, True, cost + charge(c, t) + jc + p[j][k])

    def start(j, cost):
        if j == m:
            return
        for f in range(n):
            go(j + 1, f, 1, True, cost + int(ent[f]) + p[j][f])
        start(j + 1, cost + C_INS)

    start(0, 0)
    return best


VOCAB = "the a dog cat sat ran on mat big red fox sun went to shop and he she it was".split()


def random_case(rng: random.Random, n: int, m: int):
    toks = [rng.choice(VOCAB) for _ in range(n)]
    sid, cur = [], 0
    for i in range(n):
        if i and rng.random() < 0.3:
            cur += 1
        sid.append(cur)
    words = [rng.choice(VOCAB + ["dgo", "cta", "xyz"]) for _ in range(m)]
    return toks, sid, words, rng.randrange(n)


def check(trials: int) -> int:
    rng = random.Random(7)
    vocab = set(VOCAB)
    bad = 0
    for _ in range(trials):
        n, m = rng.randint(1, 6), rng.randint(1, 4)
        toks, sid, words, pcur = random_case(rng, n, m)
        p = pair_costs(words, toks, vocab.__contains__)
        for fb in (False, True):
            a, b = dp_vectorised(sid, p, pcur, fb), dp_brute(sid, p, pcur, fb)
            if a != b:
                bad += 1
                if bad <= 5:
                    print("MISMATCH", fb, toks, sid, words, pcur, a, b)
    return bad


def page(n: int, rng: random.Random):
    words = [rng.choice(VOCAB) for _ in range(n)]
    sid, cur, k = [], 0, 0
    for _ in range(n):
        sid.append(cur)
        k += 1
        if k >= rng.randint(6, 14):
            cur, k = cur + 1, 0
    return words, sid


def bench(n: int = 400, m: int = 25, runs: int = 200) -> tuple[float, float]:
    rng = random.Random(1)
    toks, sid = page(n, rng)
    vocab = set(VOCAB)
    times = []
    for r in range(runs):
        start = rng.randrange(0, n - m)
        words = [w if rng.random() > 0.2 else rng.choice(VOCAB) for w in toks[start:start + m]]
        t0 = time.perf_counter()
        p = pair_costs(words, toks, vocab.__contains__)
        dp_vectorised(sid, p, pcur=rng.randrange(n))
        times.append(time.perf_counter() - t0)
    times.sort()
    return statistics.median(times) * 1000, times[int(0.95 * len(times)) - 1] * 1000


if __name__ == "__main__":
    bad = check(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
    print(f"oracle mismatches: {bad}")
    p50, p95 = bench()
    print(f"page pass n=400 m=25: p50 {p50:.1f} ms, p95 {p95:.1f} ms")
