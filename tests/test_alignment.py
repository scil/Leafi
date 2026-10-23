"""ADR-0013 v2 walkthroughs and the testing.md alignment scenarios. Never mocked.

Status codes: U unattempted, P provisional, C committed, M candidate, S settled, R unread. Utterances are
typed (confident) unless `confs` is given.
"""

from __future__ import annotations

from leafi.core.wordinfo import TableWordInfo
from leafi.study.alignment import (
    CandidateCreated,
    CandidateWithdrawn,
    FirstWordsPrompt,
    LineSkipped,
    OriginSupplied,
    ReadingState,
    SentenceReached,
    Unaligned,
    align,
    back,
    best_path,
    complete_sentence,
    opened,
    pause_completes,
    resumed,
    retry_result,
    settle,
    skip_read,
    supply,
)

REAL = """the a an and to of in on at it he she we they i was is were had has have dog dogs cat cats sat ran run
little brown walked walk slowly mat cap house horse home big bag red bird blue see saw park went want shop ship
milk mum can snack after this that old fox clever smiled smiles at edge wood lived every morning down river drink
fast colour color run card car through threw dug""".split()
INFO = TableWordInfo(
    words=REAL,
    phones={"colour": {"kVl@"}, "color": {"kVl@"}, "through": {"Tru:"}, "threw": {"Tru:"}},
    lemmas={"smiled": {"smile"}, "smiles": {"smile"}, "walked": {"walk"}, "ran": {"run"}, "dogs": {"dog"},
            "cats": {"cat"}, "had": {"have"}, "has": {"have"}},
)


class Reader:
    """Feeds utterances like the session does: align, then complete every reached sentence in order."""

    def __init__(self, text: str, info=INFO) -> None:
        self.state = ReadingState.from_text(text)
        self.seq = 0
        self.info = info
        self.events: list = []
        self.candidates_at_completion: list[list[int]] = []

    def read(self, utterance: str, confs=None, **kw):
        self.seq += 1
        words = utterance.split()
        if isinstance(confs, float):
            confs = [confs] * len(words)
        self.state, obs, events = align(self.state, words, self.seq, self.info, confs=confs, **kw)
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


# ---------------------------------------------------------------- walkthroughs (ADR-0013 v2)


def test_a_typed_one_word_per_utterance_commits_all_six():
    r = Reader("The little brown dog walked slowly.")
    for k, word in enumerate("The little brown dog walked slowly".split(), start=1):
        _, events = r.read(word)
        assert not kinds(events, Unaligned)
        if k < 6:
            assert r.state.statuses().split()[:k] == ["P"] * k
            assert r.cursors == (k, k)
    assert r.state.statuses() == "C C C C C C"
    assert all(not kinds(ev, CandidateCreated) for ev in r.events)


def test_a_spoken_lone_function_word_is_unaligned_and_skipped_by_rule_6():
    r = Reader("The little brown dog walked slowly.")
    _, ev = r.read("the", confs=0.95)
    assert ev == [Unaligned(1)]
    r.read("little", confs=0.9)
    assert r.state.statuses().split()[:2] == ["R", "P"]


def test_b_terminal_substitution_becomes_a_candidate():
    r = Reader("The dog ran.")
    obs, events = r.read("The dog red.")
    assert [o.kind for o in obs] == ["matched", "matched", "substituted"]
    assert kinds(events, CandidateCreated) == [CandidateCreated(2, "ran", "red", 2, "substitution")]
    assert r.state.statuses() == "C C M" and r.cursors == (3, 3)
    r.state = settle(r.state, [2])
    assert r.state.statuses() == "C C S" and r.state.page_complete()


def test_c_self_correction_in_the_next_utterance_withdraws_the_candidate():
    r = Reader("The little cat sat on the mat.")
    _, ev1 = r.read("The little cap")
    assert r.state.statuses() == "P P M U U U U" and r.cursors == (3, 3)
    assert kinds(ev1, CandidateCreated) == [CandidateCreated(2, "cat", "cap", 2, "substitution")]
    _, ev2 = r.read("cat sat on the mat.")
    assert kinds(ev2, CandidateWithdrawn) == [CandidateWithdrawn(2, "self_corrected")]
    assert r.state.statuses() == "C C S C C C C"


def test_c_variant_a_later_match_is_a_reread_not_a_self_correction():
    r = Reader("The little cat sat on the mat.")
    r.read("The little cap")
    r.seq += 1
    _, ev = r.read("cat sat on the mat")
    assert kinds(ev, CandidateWithdrawn) == [CandidateWithdrawn(2, "reread")]


def test_d_identical_sentences_advance_and_back_reopens_only_the_current_sentence():
    r = Reader("I can see it. I can see it.")
    r.read("I can see it")
    _, ev = r.read("I can see it")
    assert kinds(ev, SentenceReached) == [SentenceReached(2)]
    st = back(r.state, 1)
    assert st.statuses() == "C C C C U U U U" and (st.pcur, st.ccur) == (4, 4) and st.completed == {1}


def test_e_trailing_word_is_an_insertion_not_a_substitution_in_the_next_sentence():
    r = Reader("The dog ran. The cat sat.")
    obs, ev = r.read("The dog ran away.")
    assert obs[-1].kind == "inserted" and obs[-1].heard == "away" and obs[-1].token_start == 3
    assert not kinds(ev, CandidateCreated)
    assert r.state.statuses() == "C C C U U U"


PHONETIC = "Alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike."


def test_f_a_skipped_line_of_six_tokens_is_unread_and_creates_no_candidate():
    r = Reader(PHONETIC)
    obs, ev = r.read("alpha bravo charlie delta kilo lima mike")
    assert kinds(ev, LineSkipped) == [LineSkipped(6, 4, 10)]
    assert not kinds(ev, CandidateCreated)
    assert r.state.statuses() == "C C C C R R R R R R C C C"


def test_f_two_words_after_a_skip_are_the_named_limit():
    r = Reader(PHONETIC)
    _, ev = r.read("alpha bravo charlie delta kilo lima")
    assert [e.token_index for e in kinds(ev, CandidateCreated)] == [4, 5]  # substitutions 20 < deletion 23


G_PAGE = ("At the edge of the wood lived a clever old fox. Every morning he walked down to the river to drink. "
          "She smiled at the clever fox.")


def test_g_lost_start_reaches_the_sentence_with_no_false_candidate():
    st = ReadingState.from_text(G_PAGE)
    words = "she smiled at the clever fox".split()
    fast = best_path(st, words, INFO)
    assert fast.cost == 44
    r = Reader(G_PAGE)
    _, ev = r.read(" ".join(words))
    assert not kinds(ev, CandidateCreated)
    assert r.state.statuses() == " ".join(["R"] * 21 + ["C"] * 6)


def test_h_real_word_misreading_is_a_candidate():
    r = Reader("The horse ran.")
    _, ev = r.read("the house ran")
    assert kinds(ev, CandidateCreated) == [CandidateCreated(1, "horse", "house", 1, "substitution")]


def test_h_low_confidence_substitution_is_observed_only():
    r = Reader("The horse ran.")
    _, ev = r.read("the house ran", confs=[0.9, 0.4, 0.9])
    assert not kinds(ev, CandidateCreated)
    assert r.state.statuses() == "C C C"


def test_h_typed_non_word_is_fuzzy_credit():
    r = Reader("The horse ran.")
    obs, ev = r.read("the hosre ran")
    assert [o.kind for o in obs] == ["matched"] * 3 and obs[1].pair_class == "fuzzy"
    assert not kinds(ev, CandidateCreated)


def test_i_reread_inside_an_utterance_is_a_repetition_not_an_insertion():
    r = Reader("The dog ran fast.")
    obs, ev = r.read("the dog the dog ran fast")
    assert not [o for o in obs if o.kind == "inserted"]
    assert sum(o.repeat for o in obs) == 2
    assert not kinds(ev, CandidateCreated)


def test_i_substitution_then_reread_is_a_self_correction_with_no_miscue():
    st = ReadingState.from_text("The dog ran fast.")
    assert best_path(st, "the dog red the dog ran fast".split(), INFO).cost == 16
    r = Reader("The dog ran fast.")
    obs, ev = r.read("the dog red the dog ran fast")
    assert not kinds(ev, CandidateCreated)
    assert [o.self_correction for o in obs if o.kind == "substituted"] == [True]


def test_i_inserted_attempt_before_the_word_is_marked_self_correction():
    r = Reader("The little cat sat.")
    obs, ev = r.read("the little cap cat sat")
    ins = [o for o in obs if o.kind == "inserted"]
    assert len(ins) == 1 and ins[0].heard == "cap" and ins[0].self_correction
    assert not kinds(ev, CandidateCreated)


def test_m_chatter_is_unaligned_and_prompts_once_after_three():
    r = Reader("The dog ran fast. It was fun.")
    for k in range(4):
        _, ev = r.read("can i have a snack after this")
        assert ev[0] == Unaligned(7)
        assert kinds(ev, FirstWordsPrompt) == ([FirstWordsPrompt()] if k == 2 else [])
    r.read("the dog ran")
    assert (r.state.unaligned_run, r.state.prompted) == (0, False)


def test_n_lone_function_word_spoken_never_anchors_typed_does():
    r = Reader("We went to the park.")
    r.read("we went to")
    _, ev = r.read("the", confs=0.95)
    assert ev == [Unaligned(1)]
    _, ev = r.read("the")
    assert not kinds(ev, Unaligned)


def test_o_numbers_join_heard_number_words():
    r = Reader("He was 21.")
    obs, ev = r.read("he was twenty one")
    assert [o.pair_class for o in obs] == ["exact", "exact", "join"] and not kinds(ev, CandidateCreated)
    r = Reader("Twenty one cats sat.")
    obs, _ = r.read("twenty one cats sat")
    assert [o.pair_class for o in obs] == ["exact"] * 4
    r = Reader("It was 1990 then.")
    obs, _ = r.read("it was nineteen ninety then")
    assert obs[2].pair_class == "join"
    r = Reader("He had 105 cats.")
    obs, _ = r.read("he had one hundred and five cats")
    assert obs[2].pair_class == "join"


def test_p_inflection_is_observed_by_default_and_practised_on_request():
    r = Reader("She smiled at the fox.")
    obs, ev = r.read("she smiles at the fox")
    assert obs[1].pair_class == "inflection" and not kinds(ev, CandidateCreated)
    r = Reader("She smiled at the fox.")
    _, ev = r.read("she smiles at the fox", inflections="practise")
    assert [e.token_index for e in kinds(ev, CandidateCreated)] == [1]
    r = Reader("The big card is red.")
    obs, ev = r.read("the big car is red")
    assert obs[2].pair_class == "substitute" and [e.token_index for e in kinds(ev, CandidateCreated)] == [2]


def test_q_chatter_with_one_page_word_is_unaligned():
    r = Reader("Mum went to the shop to buy some milk.")
    _, ev = r.read("mum can i have a snack after this")
    assert ev == [Unaligned(8)]


def test_r_one_word_sentences_are_all_reached():
    r = Reader("Run! Run! Run!")
    _, ev = r.read("run run run")
    assert kinds(ev, SentenceReached) == [SentenceReached(1), SentenceReached(2), SentenceReached(3)]


def test_s_patterned_book_keeps_the_misreading_in_the_current_sentence():
    r = Reader("I see a red bird. I see a blue cat. I see a red bird.")
    r.read("I see a red bird")
    _, ev = r.read("I see a red bird")
    assert [e.token_index for e in kinds(ev, CandidateCreated)] == [8, 9]


def test_t_a_told_word_is_never_withdrawn_by_alignment():
    r = Reader("The little brown dog walked slowly.")
    r.read("the little brown")
    r.state, ev = supply(r.state, 3, r.seq)
    assert kinds(ev, CandidateCreated) == [CandidateCreated(3, "dog", None, None, "supplied")]
    r.read("dog walked slowly")
    assert r.state.statuses() == "C C C M C C"
    st = back(r.state, 1)
    st, ev2 = supply(st, 3, 9)
    assert ev2[:1] == [OriginSupplied(3)]


def test_u_slow_reader_lone_misreading_and_pause():
    r = Reader("The little brown dog walked slowly.")
    r.read("the little", confs=0.9)
    r.read("brown", confs=0.9)
    _, ev = r.read("dug", confs=0.9)
    assert kinds(ev, CandidateCreated) == [CandidateCreated(3, "dog", "dug", 0, "substitution")]
    assert pause_completes(r.state) is None  # walked and slowly are content words still unattempted
    r.read("walked", confs=0.9)
    r.read("slowly", confs=0.9)
    assert r.state.statuses() == "C C C M C C"


def test_u_interjection_is_not_a_lone_misreading():
    r = Reader("We drink the milk.")
    r.read("we drink the", confs=0.9)
    _, ev = r.read("mum", confs=0.95)
    assert ev == [Unaligned(1)]


def test_w_page_pass_runs_across_dropped_articles():
    lead = " ".join(f"w{i}" for i in range(20)) + ". "
    r = Reader(lead + "The dog saw the cat in the park.")
    _, ev = r.read("dog saw cat in park")
    assert not kinds(ev, CandidateCreated)
    tail = r.state.statuses().split()[20:]
    assert tail == ["R", "C", "C", "C", "C", "C", "C", "C"]


# ---------------------------------------------------------------- other rules


def test_short_internal_skip_is_a_deletion_candidate():
    r = Reader("The big brown dog ran home.")
    obs, ev = r.read("The big dog ran home")
    assert [o.kind for o in obs].count("deleted") == 1
    assert kinds(ev, CandidateCreated) == [CandidateCreated(2, "brown", None, 2, "deletion")]


def test_deleted_function_word_is_observed_not_a_candidate():
    r = Reader("The dog sat on the mat.")
    obs, ev = r.read("the dog sat the mat")
    assert [o for o in obs if o.kind == "deleted"][0].function_word
    assert not kinds(ev, CandidateCreated)


def test_phones_class_credits_homophones():
    r = Reader("The colour is red.")
    obs, ev = r.read("the color is red")
    assert obs[1].pair_class == "phones" and not kinds(ev, CandidateCreated)


def test_completion_by_pause_or_typed_line_end_keeps_cursor_invariant():
    st = ReadingState.from_text("The dog ran. It sat.")
    st, _, _ = align(st, "The dog ran".split(), 1, INFO)
    st, _ = complete_sentence(st, 1)
    assert (st.pcur, st.ccur) == (3, 3)
    st2 = ReadingState.from_text("The big dog. It sat.")
    st2, _, _ = align(st2, "The big".split(), 1, INFO)
    assert pause_completes(st2) is None  # "dog" is a content word still unattempted


def test_skip_in_read_completes_and_moves_to_next_sentence():
    st = ReadingState.from_text("The dog ran fast. It sat.")
    st, _, _ = align(st, "The dog red".split(), 1, INFO)
    st, sid, cands = skip_read(st)
    assert sid == 1 and cands == [2] and (st.pcur, st.ccur) == (4, 4)


def test_opened_rest_clamps_to_a_sentence_start_and_marks_touched_unread():
    st = ReadingState.from_text("The dog ran. The cat sat. It was fun.")
    st2 = opened(st, 5, touched={1})
    assert (st2.pcur, st2.ccur) == (3, 3) and st2.statuses() == "C R C U U U U U U" and st2.completed == {1}
    assert opened(st, st.n).pcur == st.n
    assert opened(st, 5, range_from=0).statuses() == "U U U U U U U U U"


def test_resume_from_committed_cursor():
    r = Reader("The dog ran. The cat sat. It was fun.")
    r.read("The dog ran")
    r.read("The cat")
    st = resumed(r.state)
    assert (st.pcur, st.ccur) == (3, 3) and st.statuses() == "C C C U U U U U U" and st.completed == {1}


def test_state_round_trips_through_json():
    r = Reader("The little cat sat on the mat.")
    r.read("The little cap")
    r.state, _ = supply(r.state, 3, 2)
    st = ReadingState.from_json("The little cat sat on the mat.", r.state.to_json())
    assert st.to_json() == r.state.to_json() and st.tokens[3].supplied


def test_retry_result_passes_only_exact_phones_or_join():
    assert retry_result(["through"], "through", INFO) == "pass"
    assert retry_result(["threw"], "through", INFO) == "pass"
    assert retry_result(["throgh"], "through", INFO) == "fail"  # fuzzy never passes a retry
    assert retry_result(["thrill"], "through", INFO, [0.3]) == "unclear"
    assert retry_result(["twenty", "one"], "21", INFO) == "pass"
    assert retry_result(["it's", "through"], "through", INFO) == "pass"
