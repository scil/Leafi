"""ADR-0013 v2 → Performance: `align` ≤ 100 ms p95 for a 400-token page and 25 heard words, page pass
included, with WordInfo answers precomputed. Timing depends on the machine, so it is hardware-marked."""

from __future__ import annotations

import random
import time

import pytest

from leafi.core.wordinfo import TableWordInfo
from leafi.study.alignment import ReadingState, align

VOCAB = "the a dog cat sat ran on mat big red fox sun went to shop and he she it was".split()


@pytest.mark.hardware
def test_align_p95_under_100_ms_on_a_400_token_page():
    rng = random.Random(1)
    words, text = [], []
    for _i in range(400):
        w = rng.choice(VOCAB)
        words.append(w)
        text.append(w + ("." if rng.random() < 0.1 else ""))
    page = " ".join(text) + "."
    info = TableWordInfo(words=VOCAB)
    times = []
    for _ in range(100):
        st = ReadingState.from_text(page)
        st.pcur = st.ccur = rng.randrange(0, 380)
        start = rng.randrange(0, 375)
        heard = [w if rng.random() > 0.3 else rng.choice(VOCAB) for w in words[start:start + 25]]
        t0 = time.perf_counter()
        align(st, heard, 1, info, confs=[0.9] * 25)
        times.append(time.perf_counter() - t0)
    times.sort()
    assert times[94] < 0.100, times[94]
