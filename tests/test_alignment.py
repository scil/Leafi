"""ADR-0013 walkthroughs (a)-(f) and the testing.md alignment scenarios. Never mocked.

Status codes: U unattempted, P provisional, C committed, M candidate, S settled, R unread.
"""

from __future__ import annotations

from leafi.study.alignment import (
    CandidateCreated,
    CandidateWithdrawn,
    LineSkipped,
    ReadingState,
    SentenceReached,
    Unanchored,
    align,
    back,
    best_path,
    complete_sentence,
    pause_completes,
    resumed,
    retry_matches,
    settle,
    skip_read,
)


class Reader:
    """Feeds utterances like the session does: align, then complete every reached sentence in order."""

    def __init__(self, text: str) -> None:
        self.state = ReadingState.from_text(text)
        self.seq = 0
        self.events: list = []
        self.candidates_at_completion: list[list[int]] = []

    def read(self, utterance: str):
        self.seq += 1
        self.state, obs, events = align(self.state, utterance.split(), self.seq)
        self.events.append(events)
        for e in events:
            if isinstance(e, SentenceReached):
                self.state, cands = complete_sentence(self.state, e.sentence_id)
                self.candidates_at_completion.append(cands)
        return obs, events

    @property
    def cursors(self) -> tuple[int, int]:
        return self.state.pcur, self.state.ccur


def kinds(events, cls):
    return [e for e in events if isinstance(e, cls)]


def test_a_one_word_per_utterance_commits_all_six():
    r = Reader("The little brown dog walked slowly.")
    for k, word in enumerate("The little brown dog walked slowly".split(), start=1):
        _, events = r.read(word)
        assert not kinds(events, Unanchored)
        if k < 6:
            assert r.state.statuses().split()[:k] == ["P"] * k
            assert r.cursors == (k, k)
            assert not kinds(events, SentenceReached)
    assert kinds(r.events[-1], SentenceReached) == [SentenceReached(1)]
    assert r.state.statuses() == "C C C C C C"
    assert r.cursors == (6, 6)
    assert all(not kinds(ev, CandidateCreated) for ev in r.events)


def test_b_terminal_substitution_becomes_a_candidate_and_practice_settles_it():
    r = Reader("The dog ran.")
    obs, events = r.read("The dog red.")
    assert [o.kind for o in obs] == ["matched", "matched", "substituted"]
    assert kinds(events, CandidateCreated) == [CandidateCreated(2, "ran", "red", 2)]
    assert kinds(events, SentenceReached) == [SentenceReached(1)]
    assert r.state.statuses() == "C C M"
    assert r.cursors == (3, 3)
    assert r.candidates_at_completion == [[2]]
    # PRACTICE: no retry within PRACTICE_RETRY_S → unsure(idle) (session); the token becomes settled
    r.state = settle(r.state, [2])
    assert r.state.statuses() == "C C S"
    assert r.state.page_complete()


def test_c_self_correction_in_the_next_utterance_withdraws_the_candidate():
    r = Reader("The little cat sat on the mat.")
    _, ev1 = r.read("The little cap")
    assert r.state.statuses() == "P P M U U U U" and r.cursors == (3, 3)
    assert kinds(ev1, CandidateCreated) == [CandidateCreated(2, "cat", "cap", 2)]
    assert not kinds(ev1, SentenceReached)
    _, ev2 = r.read("cat sat on the mat.")
    assert kinds(ev2, CandidateWithdrawn) == [CandidateWithdrawn(2, "self_corrected")]
    assert r.state.statuses() == "C C S C C C C"
    assert r.cursors == (7, 7)
    assert r.candidates_at_completion == [[]]  # no practice


def test_c_variant_a_later_match_is_a_reread_not_a_self_correction():
    r = Reader("The little cat sat on the mat.")
    r.read("The little cap")
    r.seq += 1  # another utterance (unanchored noise) came in between
    _, ev = r.read("cat sat on the mat")
    assert kinds(ev, CandidateWithdrawn) == [CandidateWithdrawn(2, "reread")]


def test_d_identical_sentences_advance_and_back_reopens_only_the_current_sentence():
    r = Reader("I can see it. I can see it.")
    r.read("I can see it")
    assert r.state.statuses() == "C C C C U U U U" and r.cursors == (4, 4)
    _, ev = r.read("I can see it")
    assert kinds(ev, SentenceReached) == [SentenceReached(2)]  # `completed` prevents a repeat of 1
    assert r.state.statuses() == "C C C C C C C C" and r.cursors == (8, 8)
    st = back(r.state, 1)
    assert st.statuses() == "C C C C U U U U"
    assert (st.pcur, st.ccur) == (4, 4)
    assert st.completed == {1}
    assert st.turn_id == r.state.turn_id + 1


def test_back_two_reopens_current_and_the_one_before():
    r = Reader("I can see it. I can see it. We go.")
    r.read("I can see it")
    r.read("I can see it")
    assert r.cursors == (8, 8)
    st = back(r.state, 2)  # current = sentence 3 (pcur=8), so sentences 2..3 reopen
    assert st.statuses() == "C C C C U U U U U U"
    assert (st.pcur, st.ccur) == (4, 4) and st.completed == {1}


def test_e_trailing_word_is_an_insertion_not_a_substitution_in_the_next_sentence():
    r = Reader("The dog ran. The cat sat.")
    obs, ev = r.read("The dog ran away.")
    assert obs[-1].kind == "inserted" and obs[-1].heard == "away" and obs[-1].token_start == 3
    assert not kinds(ev, CandidateCreated)
    assert r.state.statuses() == "C C C U U U"
    assert r.cursors == (3, 3) and r.state.completed == {1}


def test_f_a_skipped_line_of_six_tokens_is_unread_and_creates_no_candidate():
    # With only four words before a six-token skip, jumping ahead and substituting costs 4.6 < 4.8 of
    # deletions (plan Surprises); five words before make the skip the cheapest path. A word repeated inside
    # the skipped line ("the") would tie and the lexicographic rule would match it instead.
    text = "Sam and Mia walked slowly down a long road to see that old mill by our river bank today."
    r = Reader(text)
    obs, ev = r.read("Sam and Mia walked slowly that old mill by our river bank today")
    assert kinds(ev, LineSkipped) == [LineSkipped(6, 5, 11)]
    assert not kinds(ev, CandidateCreated)
    assert not [o for o in obs if o.kind == "deleted"]
    assert r.state.statuses() == "C C C C C R R R R R R C C C C C C C C"
    assert r.cursors == (19, 19)


def test_short_internal_skip_is_a_deletion_candidate():
    r = Reader("The big brown dog ran home.")
    obs, ev = r.read("The big dog ran home")
    assert [o.kind for o in obs].count("deleted") == 1
    assert kinds(ev, CandidateCreated) == [CandidateCreated(2, "brown", None, 2)]


def test_hesitation_across_two_utterances_needs_no_penalty():
    r = Reader("The little brown dog walked slowly.")
    r.read("The little")
    assert r.state.statuses() == "P P U U U U"
    r.read("brown dog walked slowly")
    assert r.state.statuses() == "C C C C C C"
    assert all(not kinds(e, CandidateCreated) for e in r.events)


def test_reread_of_three_words_is_never_penalised():
    r = Reader("The little brown dog walked slowly to the big red barn.")
    r.read("The little brown dog walked")
    _, ev = r.read("brown dog walked slowly to the")
    assert not kinds(ev, CandidateCreated)
    assert r.state.statuses().startswith("P P P P P P P P")
    assert r.cursors == (8, 8)


def test_unattempted_suffix_is_never_deleted():
    r = Reader("One two three four five six seven eight.")
    obs, _ = r.read("One two three")
    assert [o.kind for o in obs] == ["matched"] * 3
    assert r.state.statuses() == "P P P U U U U U"
    assert r.cursors == (3, 3)


def test_sentence_restart_reads_as_progress_without_candidates():
    r = Reader("The cat sat on the mat. It was warm.")
    r.read("The cat")
    _, ev = r.read("The cat sat on the mat")
    assert not kinds(ev, CandidateCreated)
    assert kinds(ev, SentenceReached) == [SentenceReached(1)]


def test_singleton_far_from_cursor_is_unanchored_and_state_unchanged():
    r = Reader("The little brown dog walked slowly.")
    before = r.state.to_json()
    _, ev = r.read("slowly")
    assert ev == [Unanchored()]
    assert r.state.to_json() == before


def test_two_scattered_matches_without_a_run_are_unanchored():
    r = Reader("Alpha beta gamma delta epsilon zeta eta theta.")
    r.read("Alpha beta")
    _, ev = r.read("delta xx zeta")
    assert ev == [Unanchored()]


def test_reposition_page_wide_needs_a_run_of_three():
    text = "Ann has a red hat. Bob has a blue cap. Cat has a green bag. Dan has a pink box."
    st = ReadingState.from_text(text)
    st2, _, ev = align(st, "Dan has a pink".split(), 1, whole_page=True)
    assert not kinds(ev, Unanchored)
    assert st2.statuses().split()[:15] == ["R"] * 15
    assert st2.ccur == 19 and st2.pcur == 19
    _, _, ev_short = align(st, "pink box".split(), 1, whole_page=True)
    assert ev_short == [Unanchored()]


def test_fuzzy_match_counts_as_a_match():
    r = Reader("The colour is bright.")
    obs, ev = r.read("The color is bright")
    assert [o.kind for o in obs] == ["matched"] * 4
    assert not kinds(ev, CandidateCreated)


def test_numbers_and_contractions_normalise():
    r = Reader("I don't have 3 cats.")
    obs, _ = r.read("i dont have three cats")
    assert [o.kind for o in obs] == ["matched"] * 5


def test_completion_by_pause_or_typed_line_end_keeps_cursor_invariant():
    st = ReadingState.from_text("The dog ran. It sat.")
    st, _, _ = align(st, "The dog".split(), 1)
    assert (st.pcur, st.ccur) == (2, 2)
    sid = pause_completes(st)
    assert sid == 1
    st, cands = complete_sentence(st, sid)
    assert st.statuses() == "C C R U U"
    assert (st.pcur, st.ccur) == (3, 3) and st.ccur <= st.pcur and cands == []


def test_pause_far_from_sentence_end_does_not_complete():
    st = ReadingState.from_text("One two three four five six.")
    st, _, _ = align(st, "One two".split(), 1)
    assert pause_completes(st) is None


def test_skip_in_read_completes_and_moves_to_next_sentence():
    st = ReadingState.from_text("The dog ran fast. It sat.")
    st, _, _ = align(st, "The dog red".split(), 1)
    st, sid, cands = skip_read(st)
    assert sid == 1 and cands == [2]
    assert (st.pcur, st.ccur) == (4, 4)
    assert st.statuses() == "C C M R U U"


def test_resume_from_committed_cursor():
    r = Reader("The dog ran. The cat sat. It was fun.")
    r.read("The dog ran")
    r.read("The cat")
    st = resumed(r.state)
    assert (st.pcur, st.ccur) == (5, 5)
    assert st.statuses() == "C C C C C U U U U"
    assert st.completed == {1}


def test_state_round_trips_through_json():
    r = Reader("The little cat sat on the mat.")
    r.read("The little cap")
    st = ReadingState.from_json("The little cat sat on the mat.", r.state.to_json())
    assert st.to_json() == r.state.to_json()
    assert st.tokens[2].created_by == 1


def test_retry_matching():
    assert retry_matches(["through"], "through")
    assert retry_matches(["Through!"], "through")
    assert retry_matches(["throgh"], "through")
    assert not retry_matches(["cap"], "cat")
    assert not retry_matches(["red"], "ran")


def test_tie_break_is_unique_and_deterministic():
    st = ReadingState.from_text("a b a b a b.")
    p1 = best_path(st.tokens, 0, st.n, ["a", "b"], 2)
    p2 = best_path(st.tokens, 0, st.n, ["a", "b"], 2)
    assert [(o.index, o.op) for o in p1] == [(o.index, o.op) for o in p2] == [(2, 0), (3, 0)]
