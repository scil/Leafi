"""The `code`-owned activities (ADR-0017 §3.1; ADR-0013 owns the reading and practice rules).

Each runs as `await KINDS[kind](world, activity, activity_id) -> (status, outcome)`. Cancellation (the latch) and
`StaleInput` pass through to the loop's `run_activity`, which maps them to a status; an activity returns only
its own statuses. Nothing is practised inside reading and nothing is said there beyond §6.1.
"""

from __future__ import annotations

import html
import logging
import math
import time

from leafi.core import learner_store
from leafi.core.ports import Display, Utterance
from leafi.core.storage import dumps, loads, now_iso
from leafi.core.text import words
from leafi.study import cards, coach, controls, corrections, item_status, knowledge, miscues, pages, phrases
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
    complete_sentence,
    pause_completes,
    retry_result,
    skip_read,
    supply,
)
from leafi.study.harness import rows
from leafi.study.harness.state import Activity
from leafi.study.harness.world import PageRequest, World

log = logging.getLogger("leafi.harness.activities")

PRON_CONFIRM_BELOW = 0.5  # scorer threshold for `confirmed` (only when PRON_AUTO_JUDGE is on)
EASES = {"again": 1, "hard": 2, "good": 3, "easy": 4}
OUTCOME_OF = {"pass": "matched", "fail": "disagreed", "unclear": "unclear"}


def _store_utterance(w: World, u: Utterance, kind: str) -> int:
    return learner_store.insert_named(  # fenced by the session's learner (ADR-0021 E9)
        w.store, "utterances", page_read_id=w.read_id, page_revision_id=w.rev.id if w.rev else None,
        session_id=w.s.session_id, text=u.text, kind=kind, created_at=now_iso(),
        words=dumps([[x.text, x.start_s, x.end_s, x.conf] for x in u.words]))


def _confident(u: Utterance) -> bool:
    """§3.4 (amended 2026-10-25): the one predicate, also false for every panel line."""
    from leafi.study.brain.scoring import counts_as_answer

    return counts_as_answer(u)


def _panel(u: Utterance) -> bool:
    return u.source == controls.PANEL


def _panel_data(u: Utterance, ctl: controls.Control | None) -> bool:
    """A panel line that is no command: the owner's text, never the learner's reading, attempt or question."""
    return _panel(u) and ctl is None


def _page_turn(w: World, ctl: controls.Control) -> None:
    """A page turn: what the learner turned to is the next page read's request (§8.2)."""
    text = None
    if ctl.kind == "page" and ctl.path is not None:
        try:
            text = ctl.path.read_text(encoding="utf-8")
        except OSError:
            log.warning("page text file could not be read")
    w.pending = PageRequest(ctl.n if ctl.kind == "page" else None, text)
    if ctl.kind == "next_page" and w.page_id is not None:
        cur = w.store.one("SELECT printed_number FROM pages WHERE id=?", (w.page_id,))["printed_number"]
        w.pending = PageRequest(cur + 1 if cur is not None else None)


# ---------------------------------------------------------------- read_listen (ADR-0013; §6.1; §8.2)


def _range_sids(st: ReadingState, rng) -> list[int]:
    ids = st.sentence_ids()
    if isinstance(rng, dict):
        return [i for i in ids if rng["from"] <= i <= rng["to"]]
    return ids


async def _open(w: World, act: Activity, aid: int) -> bool | None:
    """Acquire and open the page read; None when no page came (idle)."""
    page = act.params.get("page", "current")
    if not act.params.get("continuation"):
        w.ensure_cycle(aid)
    else:
        w.store.execute("UPDATE activities SET cycle_id=? WHERE id=?", (w.s.cycle_id, aid))
    if page == "current" and w.page_id is not None and w.pending is None:
        return w.open_page_read(w.page_id, act.params.get("range", "rest"))
    if page == "current":
        page = "next"
    pid = await w.acquire_page(page)
    if pid is None:
        return None
    return w.open_page_read(pid, act.params.get("range", "rest"), familiar=page == "familiar")


async def _announce(w: World, owner) -> None:
    printed = w.store.one("SELECT printed_number FROM pages WHERE id=?", (w.page_id,))["printed_number"]
    await w.inputs.line("page_ready" if w.inputs.voice else "page_ready_text", page=printed if printed else "",
                        owner=owner)


def _persist(w: World, uid: int, obs, events, st: ReadingState) -> None:
    with w.store.transaction():
        obs_ids = [w.store.insert("observations", utterance_id=uid, kind=o.kind, token_start=o.token_start,
                                  token_end=o.token_end, heard_text=o.heard, sim=o.sim, pair_class=o.pair_class,
                                  function_word=int(o.function_word), repeat=int(o.repeat),
                                  self_correction=int(o.self_correction), word_count=o.word_count,
                                  created_at=now_iso())
                   for o in obs]
        for e in events:
            if isinstance(e, CandidateCreated):
                tok = st.tokens[e.token_index]
                tok.miscue_id = miscues.create(
                    w.store, observation_id=obs_ids[e.observation_index] if e.observation_index is not None else None,
                    page_read_id=w.read_id, revision_id=w.rev.id, expected=e.expected, token_index=e.token_index,
                    char_span=tok.span, heard=e.heard, cycle_id=w.s.cycle_id, origin=e.origin)
            elif isinstance(e, CandidateWithdrawn):
                mid = st.tokens[e.token_index].miscue_id
                if mid:
                    miscues.set_status(w.store, mid, "withdrawn", reason=e.reason)
            elif isinstance(e, OriginSupplied):
                mid = st.tokens[e.token_index].miscue_id
                if mid:
                    w.store.execute("UPDATE miscues SET origin='supplied' WHERE id=?", (mid,))
        w.state = st
        w.save_state()


def _complete_reached(w: World, events) -> None:
    for sid in [e.sentence_id for e in events if isinstance(e, SentenceReached)]:
        if sid not in w.state.completed:
            w.state, _ = complete_sentence(w.state, sid)  # candidates stay candidates: owned by the cycle
    w.save_state()


async def _reading_utterance(w: World, u: Utterance) -> None:
    if u.typed and not u.words:  # an empty typed line is a line end, never an alignment
        sid = pause_completes(w.state) if u.line_end else None
        if sid is not None:
            w.state, _ = complete_sentence(w.state, sid)
            w.save_state()
        return
    w.seq += 1
    uid = _store_utterance(w, u, "reading")
    confs = None if u.typed else [x.conf for x in u.words]
    st, obs, events = align(w.state, [x.text for x in u.words], w.seq, w.word_info, confs=confs)
    _persist(w, uid, obs, events, st)
    if any(isinstance(e, Unaligned) for e in events):
        if any(isinstance(e, FirstWordsPrompt) for e in events):
            await w.inputs.line("reposition")  # recovery dialogue, always allowed (§6.1)
        return
    if any(isinstance(e, LineSkipped) for e in events):
        await w.inputs.line("line_skipped")
    _complete_reached(w, events)
    if u.typed and u.line_end and not any(isinstance(e, SentenceReached) for e in events):
        sid = pause_completes(w.state)
        if sid is not None:
            w.state, _ = complete_sentence(w.state, sid)
            w.save_state()


async def _explain(w: World, target_text: str | None) -> None:
    """Without a Brain (until M7) an explanation is unavailable; the question is still recorded as an item."""
    st = w.state
    target = coach.find_on_page(st, target_text) if target_text else None
    cur = st.current_sentence() or (st.sentence_ids() or [1])[-1]
    sentence = coach.sentence_text(w.rev.text, st, cur) if st.n else ""
    await w.inputs.line("explain_wait", target=target or "this sentence")
    await w.inputs.line("explain_unavailable")
    kind = "word" if target and " " not in target else "phrase"
    item = knowledge.upsert_item(w.store, w.s.learner_id, kind, target or sentence)
    knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain", revision_id=w.rev.id,
                            context_sentence=sentence)


async def _correct(w: World, ctl: controls.Control, uid: int, u: Utterance) -> None:
    if not ctl.old or not ctl.text:
        await w.inputs.line("noop")
        return
    st = w.state
    near = st.tokens[min(st.pcur, st.n - 1)].start if st.n else 0
    m = max(1, len(words(ctl.old)))
    lo = max(0, st.ccur - 6, st.sentence_start(st.ccur)) if st.ccur < st.n else max(0, st.n - 12)
    hi = min(st.n, st.pcur + math.ceil(1.5 * m) + 8)
    window = (st.tokens[lo].start, st.tokens[hi - 1].end) if st.n and hi > lo else None
    span = corrections.locate(w.rev.text, ctl.old, near, window) or corrections.locate(w.rev.text, ctl.old, near)
    source = "parent" if _panel(u) else "text" if u.typed else "voice"  # a panel fix is the owner's (design D8)
    if span is None:
        await w.inputs.line("correction_not_found", old=ctl.old)
        corrections.record_unlocated(w.store, revision_id=w.rev.id, old_text=ctl.old, new_text=ctl.text,
                                     source=source, learner_id=w.s.learner_id, utterance_id=uid)
        await w.inputs.line("correction_saved")
        return
    res = corrections.apply_correction(w.store, page_id=w.page_id, revision_id=w.rev.id, char_start=span[0],
                                       char_end=span[1], new_text=ctl.text, source=source,
                                       learner_id=w.s.learner_id, utterance_id=uid, state=w.state,
                                       book_id=w.book_id)
    w.rev, w.state = pages.revision(w.store, res.revision_id), res.state
    w.save_state()
    w.s.latch.epoch.revision_id = res.revision_id
    w.s.latch.epoch.bump()  # a correction bumps the epoch (§1)
    await w.inputs.line("correction_thanks", new=ctl.text)


_HINT_YES = {"yes please", "please", "ok please", "okay please", "sure please"}
_HINT_NO = {"no thank you", "not now", "no thanks"}


def _hint_reply(u: Utterance) -> str | None:
    """"yes" or "no" (also "yes please", "no thank you", "not now"); None: not an answer to the hint offer. A panel
    line answers only by `/yes` or `/no`."""
    if not _panel(u):
        flat = " ".join(u.text.lower().replace(",", " ").replace("’", "'").strip(" .!?").split())
        if flat in _HINT_YES:
            return "yes"
        if flat in _HINT_NO:
            return "no"
    ctl = controls.of(u)
    return ctl.kind if ctl is not None and ctl.kind in ("yes", "no") else None


async def _offer_hint(w: World, owner) -> Utterance | None:
    """§6.1 `stuck_only`: "Want a hint?"; on yes Leafi says the word and the token becomes `supplied`. Asked under
    the page read's prompt (D21); only yes and no are its answers: any other reply is returned for `read_listen` to
    dispatch, so a control is never read as reading and a posted skip is never dropped."""
    st = w.state
    if st.pcur >= st.n:
        return None
    await w.inputs.line("hint_offer", owner=owner)
    u = await w.inputs.listen(float(w.s.settings["negotiation.ask_s"]), owner, accepts_page=True)
    w.s.checkpoint()
    if u is None:
        return None
    reply = _hint_reply(u)
    if reply is None:
        return u
    if reply != "yes":
        return None
    i = st.pcur
    await w.inputs.line("hint_word", word=st.tokens[i].text)
    w.seq += 1
    uid = _store_utterance(w, u, "control")
    new, events = supply(st, i, w.seq)
    _persist(w, uid, [], events, new)
    _complete_reached(w, events)
    return None


def _late_pages(w: World, aid: int) -> Utterance | None:
    """D21: the newest page turn of this activity's ended prompts; their skips are dropped (the question is past)."""
    page = None
    for item in w.inputs.take_late(lambda o: isinstance(o, tuple) and o[:2] == ("act", aid)):
        if item.kind == "page":
            page = item.u
    return page


def _self_corrections(w: World) -> int:
    return w.store.one("SELECT COUNT(*) AS n FROM observations o JOIN utterances u ON u.id = o.utterance_id "
                       "WHERE u.page_read_id=? AND o.self_correction=1", (w.read_id,))["n"]


async def read_listen(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    s, io, cfg = w.s, w.inputs, w.settings
    w.activity_started = time.monotonic()
    opened = await _open(w, act, aid)
    if opened is None:
        s.latch.terminate("idle_session")
        return "idle_session", {}
    owner = ("page", w.read_id)  # D21: one prompt for the whole page read, the hint offer included
    await _announce(w, owner)
    target = _range_sids(w.state, act.params.get("range", "rest"))
    before = set(w.state.completed)
    interrupt = s.settings["reading.interrupt"]
    back_s, prompt_s = s.settings["reading.silence_backchannel_s"], s.settings["reading.silence_prompt_s"]
    encouraged = False
    io.page_open = True

    def outcome() -> dict:
        return {"page_read_id": w.read_id, "sentences": len(w.state.completed - before)}

    try:
        idle, cued, hinted, handed = 0.0, False, None, None
        while True:
            if set(target) <= w.state.completed:
                if (w.state.page_complete() and not encouraged and s.settings["reading.encourage"] != "none"
                        and _self_corrections(w)):
                    await io.line("encourage")  # page end: at most one (§6.1)
                    encouraged = True
                return "completed", outcome()
            timeout = cfg.sentence_pause_s if io.voice else cfg.study_idle_s
            if handed is not None:  # the hint offer's reply that was not yes or no (D21)
                u, handed = handed, None
            else:
                u = await io.listen(timeout, owner, accepts_page=True)
            s.checkpoint()
            if u is None:
                if not io.voice:
                    s.latch.terminate("idle_session")
                    return "idle_session", outcome()
                idle += timeout
                sid = pause_completes(w.state)
                if sid is not None:
                    w.state, _ = complete_sentence(w.state, sid)
                    w.save_state()
                    if w.activity_over():
                        return "completed", outcome()
                    continue
                if interrupt != "never" and idle >= back_s and not cued:
                    await w.inputs.hub.show(Display("status", "…"))  # soft cue on Faces
                    cued = True
                if interrupt != "never" and idle >= back_s + prompt_s and hinted != w.state.pcur:
                    hinted = w.state.pcur
                    handed = await _offer_hint(w, owner)
                    if handed is not None:
                        continue
                if idle >= cfg.study_idle_s:
                    s.latch.terminate("idle_session")
                    return "idle_session", outcome()
                continue
            idle, cued = 0.0, False
            if s.take_skip():  # skip completes the current sentence (§3.1)
                w.state, _sid, _ = skip_read(w.state)
                w.save_state()
                continue
            ctl = controls.of(u)
            if _panel_data(u, ctl) or (_panel(u) and ctl.kind == "explain"):
                await io.line("noop")  # §3.4 as amended: the owner's text is never the learner's reading
                continue
            if ctl is None:
                n_before = len(w.state.completed)
                await _reading_utterance(w, u)
                if len(w.state.completed) > n_before and w.activity_over():
                    return "completed", outcome()
                continue
            if ctl.kind in ("explain", "fix"):
                uid = _store_utterance(w, u, "question" if ctl.kind == "explain" else "correction")
                if ctl.kind == "explain":
                    await _explain(w, ctl.text)
                else:
                    await _correct(w, ctl, uid, u)
                continue
            _store_utterance(w, u, "control")
            if ctl.kind in ("page", "next_page"):
                _page_turn(w, ctl)  # completes nothing, settles nothing (ADR-0013 → Page turns)
                return "page_turned", outcome()
            if ctl.kind == "back":
                if not any(t.status != "unattempted" for t in w.state.tokens):
                    await io.line("back_no_page")
                w.state = back(w.state, ctl.n or 1)
                w.save_state()
                s.latch.epoch.bump()
                continue
            await io.line("noop")
    finally:
        io.page_open = False
        if s.latch.terminal == "stop":  # ADR-0013 control table: stop completes the current sentence by (iii)
            sid = w.state.current_sentence()
            if sid is not None and sid not in w.state.completed and \
                    any(t.status != "unattempted" for t in w.state.tokens if t.sentence_id == sid):
                w.state, _ = complete_sentence(w.state, sid)
                w.save_state()
        s.progress.update(outcome())  # what a jump keeps (panel design D7)
        w.end_page_read()


# ---------------------------------------------------------------- practise_errors (ADR-0013 → Practice)


async def _score(w: World, u: Utterance, word: str) -> tuple[str, float | None]:
    if not (w.settings.pron_auto_judge and u.audio_ref is not None and w.pron is not None):
        return "none", None
    try:
        result = await w.pron.score(u.audio_ref, word)
    except Exception:
        log.warning("pronunciation scorer failed", exc_info=True)
        return "none", None
    return ("acoustic", result.score) if result is not None else ("none", None)


def _candidate_context(w: World, mid: int) -> tuple[str, str]:
    r = w.store.one("SELECT m.expected, pr.reading_state, rv.text FROM miscues m JOIN page_reads pr ON pr.id = "
                    "m.page_read_id JOIN page_revisions rv ON rv.id = pr.page_revision_id WHERE m.id=?", (mid,))
    st = ReadingState.from_json(r["text"], loads(r["reading_state"]))
    tok = next((t for t in st.tokens if t.miscue_id == mid), None)
    sentence = coach.sentence_text(r["text"], st, tok.sentence_id) if tok else ""
    return r["expected"], sentence


def _finish_candidate(w: World, mid: int, evidence: str, score: float | None) -> str:
    outcomes = [r["outcome"] for r in w.store.all("SELECT outcome FROM practices WHERE miscue_id=? ORDER BY attempt",
                                                  (mid,))]
    status, why = rows.practice_final(outcomes)
    if status == "unsure" and why == "disagreed" and evidence == "acoustic" and score is not None and \
            score < PRON_CONFIRM_BELOW:
        miscues.set_status(w.store, mid, "confirmed", evidence="acoustic", score=score)
        expected, sentence = _candidate_context(w, mid)
        item = knowledge.upsert_item(w.store, w.s.learner_id, "pronunciation", expected)
        knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="miscue", context_sentence=sentence)
        status = "confirmed"
    else:
        miscues.set_status(w.store, mid, status, reason=why, evidence=evidence if evidence != "none" else None,
                           score=score)
    rows._settle_token(w.store, mid)
    if w.state is not None:
        rows.settle_in(w.state, mid)  # the World's copy too, so the snapshot never shows it open (panel D3)
    return f"{status}:{why}"


async def practise_errors(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    s, io, cfg = w.s, w.inputs, w.settings
    w.activity_started = time.monotonic()
    done: dict[int, str] = {}
    for mid in act.params["candidate_ids"]:
        if w.activity_over():
            break
        row = w.store.one("SELECT status FROM miscues WHERE id=?", (mid,))
        if row is None or row["status"] != "candidate":
            continue
        word, sentence = _candidate_context(w, mid)
        attempt = w.store.one("SELECT COUNT(*) AS n FROM practices WHERE miscue_id=?", (mid,))["n"]
        evidence, score = "none", None
        if attempt < 2:
            await io.hub.show(Display("say", sentence))
            await io.line("practice_intro", book=True, word=word)  # practice words come from the page
            await io.say(word, slow=True, book=True)
        while attempt < 2:
            owner = ("act", aid, f"{mid}.{attempt}")  # D21: each try is its own question
            await io.line("practice_retry" if attempt == 0 else "practice_again", book=True, word=word,
                          owner=owner)
            if attempt:
                await io.say(word, slow=True, book=True)
            u = await io.listen(cfg.practice_retry_s if io.voice else None, owner, accepts_page=True)
            s.checkpoint()
            if (late := _late_pages(w, aid)) is not None:  # a page turned during an earlier try
                _store_utterance(w, late, "control")
                _page_turn(w, controls.of(late))
                return "page_turned", {"practised": done}
            if u is None:
                miscues.record_practice(w.store, mid, attempt + 1, "idle")
                break
            if s.take_skip():
                miscues.record_practice(w.store, mid, attempt + 1, "skipped")
                break
            ctl = controls.of(u)
            if _panel_data(u, ctl):  # the owner's text is no attempt: no row, no budget used (design D8)
                await io.line("noop")
                continue
            if ctl is not None:
                _store_utterance(w, u, "control")
                if ctl.kind in ("page", "next_page"):
                    _page_turn(w, ctl)  # the candidate stays `candidate`; no row, no budget used
                    return "page_turned", {"practised": done}
                await io.line("back_practice" if ctl.kind == "back" else "noop")
                continue
            attempt += 1
            _store_utterance(w, u, "practice")
            evidence, score = await _score(w, u, word)
            res = retry_result([x.text for x in u.words], word, w.word_info,
                               None if u.typed else [x.conf for x in u.words])
            miscues.record_practice(w.store, mid, attempt, OUTCOME_OF[res], evidence)
            if u.audio_ref is not None:
                u.audio_ref.release()
            if res == "pass":
                break
        final = _finish_candidate(w, mid, evidence, score)
        done[mid] = final
        s.progress["practised"] = dict(done)
        await io.line("practice_withdrawn" if final.startswith("withdrawn") else
                      "practice_idle" if final.endswith("idle") else "practice_unsure")
    return "completed", {"practised": done}


# ---------------------------------------------------------------- review_anki (ADR-0004; eases 1-4)


def _retrieval(w: World, item_id: int | None, aid: int, outcome: str, evidence: str) -> None:
    """§3.4's retrieval event (household day, D17) and the item's re-fold, in one transaction."""
    if item_id is None:
        return
    cfg = w.settings
    with w.store.transaction():
        learner_store.insert(w.store, "retrieval_events", w.s.learner_id, item_id=item_id, activity_id=aid,
                             at=now_iso(), day=item_status.household_day(cfg.household_tz), outcome=outcome,
                             evidence=evidence)
        item_status.apply(w.store, item_id, cfg.review_known_interval_days)


async def review_anki(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    from leafi.study import anki

    s, io, cfg = w.s, w.inputs, w.settings
    w.activity_started = time.monotonic()
    try:
        cards = await anki.due_cards(w.store, w.anki, s.learner_id, cfg.anki_deck, act.params["max_cards"])
    except (anki.AnkiUnavailable, anki.AnkiError):
        return "completed", {"cards": 0, "unavailable": True}
    answered = 0
    await io.line("review_intro", count=len(cards))
    for i, card in enumerate(cards):
        if w.activity_over():
            break
        # a card's text may hold the learner's own words: not a book line, so TTS's detector checks it (ADR-0021 E7)
        owner = ("act", aid, f"card.{i}")  # D21: each card its own question
        await io.line("review_prompt_eases", front=card.front, owner=owner)
        while True:
            u = await io.listen(cfg.study_idle_s, owner, accepts_page=True)
            s.checkpoint()
            if (late := _late_pages(w, aid)) is not None and s.on_page is not None:
                s.on_page(late)  # D21: remembered; the next boundary opens it
            if u is None:
                s.latch.terminate("idle_session")
                return "idle_session", {"cards": answered}
            if s.take_skip():  # skips the current card
                break
            ctl = controls.of(u)
            kind = ctl.kind if ctl else None
            if kind in EASES:  # a panel ease goes to Anki as the child's review (owner, 2026-10-25), with no event
                _store_utterance(w, u, "answer")
                ease = EASES[kind]
                await anki.answer(w.store, w.anki, s.learner_id, card, ease, cfg.review_known_interval_days,
                                  tz=cfg.household_tz, activity_id=aid)
                if _confident(u):  # §3.4: an unconfident spoken answer writes no retrieval event
                    _retrieval(w, card.knowledge_item_id, aid, "fail" if ease == 1 else "success",
                               "typed" if u.typed else "heard_confident")
                answered += 1
                s.progress["cards"] = answered
                break
            await io.line("noop")
    return "completed", {"cards": answered}


# ---------------------------------------------------------------- read_aloud, break, wait, end


async def read_aloud(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    s, io = w.s, w.inputs
    w.activity_started = time.monotonic()
    opened = await _open(w, act, aid)
    if opened is None:
        s.latch.terminate("idle_session")
        return "idle_session", {}
    st = w.state
    start = st.tokens[st.ccur].sentence_id if st.ccur < st.n else None
    sids = [i for i in _range_sids(st, act.params.get("range", "rest")) if start is not None and i >= start]
    hard = set(act.content.get("hard_sentence_ids", ())) if act.content else set()  # Brain content (D15)
    await io.line("read_aloud_intro")
    said = 0
    for sid in sids:
        if w.activity_over():
            break
        text = coach.sentence_text(w.rev.text, st, sid)
        await io.hub.show(Display("say", text))
        await io.say(text, slow=sid in hard, book=True)
        s.checkpoint()
        s.take_skip()  # a skip cut this sentence; the next one follows
        said += 1
    if act.content and act.content.get("translate"):
        await io.hub.show(Display("say", act.content["translate"]))  # shown, not spoken
    return "completed", {"sentences": said, "page_read_id": w.read_id}


async def _pause(w: World, aid: int, seconds: float, line: str, *, any_input_ends: bool) -> str:
    s, io = w.s, w.inputs
    owner = ("act", aid, "pause")  # D21; a page still ends a wait, as in M6
    await io.line(line, seconds=int(seconds), owner=owner)
    await io.hub.show(Display("status", f"{int(seconds)} s"))
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        u = await io.listen(left, owner, accepts_page=True)
        s.checkpoint()
        if s.take_skip():
            return "skipped"
        if u is None or any_input_ends:
            break
    return "completed"


async def break_(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    return await _pause(w, aid, float(act.params.get("seconds", 60)), "break_start", any_input_ends=False), {}


async def wait(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    """A harness-internal break of `negotiation.wait_s`: any input ends it, so the learner can choose."""
    return await _pause(w, aid, float(act.params.get("seconds", 30)), "wait_start", any_input_ends=True), {}


async def end(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    return "completed", {}  # the closing line is `deliver`'s (§2)


# ---------------------------------------------------------------- add_cards (§7.2: the one path into Anki)


async def add_cards(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    s = w.s
    added, flagged, rejected = [], [], {}
    for item_id in act.params["item_ids"]:
        if act.content_owner == "brain":  # the generated card (D15)
            card = (act.content or {}).get("cards", {}).get(item_id)
            if card is None:
                rejected[item_id] = "no card was generated for it"
                continue
            fields = {"正面": html.escape(card["front"]), "背面": html.escape(card["back"])}
            sentence = card["sentence"]
        else:
            fields, sentence = cards.stored_text(w.store, item_id)
        verdict, reason = cards.check(w.store, s.learner_id, item_id, fields, sentence)
        if verdict == "reject":
            rejected[item_id] = reason
            continue
        try:
            learner_store.insert(w.store, "anki_outbox", s.learner_id, knowledge_item_id=item_id, op="add",
                                 state="pending", updated_at=now_iso(), front=fields["正面"], back=fields["背面"],
                                 sentence=sentence)
        except learner_store.LearnerUnavailable:  # ADR-0021 E9: the learner is being forgotten
            log.info("card not queued: the learner is being forgotten")
            rejected[item_id] = "the learner is being forgotten"
            continue
        added.append(item_id)
        if verdict == "flag":
            flagged.append(item_id)
    if added:
        await w.inputs.line("cards_added", count=len(added))
    return "completed", {"cards": len(added), "flagged": flagged, "rejected": rejected}


# ---------------------------------------------------------------- quiz (ADR-0013 → CHECK outcomes; ADR-0017 §3.4)


CHECK_ANSWER_S = 20.0  # ADR-0013: a spoken answer's time; typed answers wait `study_idle_s`
RETRIEVAL_OF = {"correct": "success", "incorrect": "fail"}


async def quiz(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    """Each generated question (its content checked at construction, D15), then the answer in the Coach voice. A
    counted answer is scored by CHECK; an unconfident spoken one, a skip, silence and every open question are
    `unavailable` and write no encounter and no retrieval event (§3.4); only `incorrect` writes an encounter."""
    s, io, cfg = w.s, w.inputs, w.settings
    w.activity_started = time.monotonic()
    results: list[str] = []
    await io.line("quiz_intro")
    for i, q in enumerate(act.content["questions"]):
        if w.activity_over():
            break
        owner = ("act", aid, f"q{i}")  # D21: each question its own prompt
        await io.ask(owner, q["text"])
        u = await io.listen(CHECK_ANSWER_S if io.voice else cfg.study_idle_s, owner, accepts_page=True)
        s.checkpoint()
        if (late := _late_pages(w, aid)) is not None and s.on_page is not None:
            s.on_page(late)  # D21: remembered; the next boundary opens it
        if u is None and not io.voice:
            s.latch.terminate("idle_session")
            return "idle_session", {"questions": len(results), "results": results}
        ctl = controls.of(u) if u is not None else None
        if ctl is not None and ctl.kind in ("page", "next_page"):
            _store_utterance(w, u, "control")
            _page_turn(w, ctl)  # a quiz cannot end `page_turned` (§3.1): the next boundary opens the page
            return "completed", {"questions": len(results), "results": results}
        skipped = s.take_skip()
        if u is not None and not skipped:
            _store_utterance(w, u, "answer")
        if q["type"] not in ("completion", "recall", "wh-"):
            outcome = "unavailable"  # open-ended, distancing: acknowledged, not scored (§3.4)
            if u is not None and not skipped:
                await io.line("quiz_thanks")
        elif u is None or skipped or not _confident(u):
            outcome = "unavailable"
        else:
            outcome = coach.check_outcome(u.text, q["answers"])
        if outcome == "correct":
            await io.line("check_correct")
        elif q["answers"]:
            await io.line("quiz_answer", answer=" ".join(q["answers"][0]))
        if outcome in RETRIEVAL_OF:
            for item in q["item_ids"]:
                _retrieval(w, item, aid, RETRIEVAL_OF[outcome], "typed" if u.typed else "heard_confident")
        if outcome == "incorrect":
            for item in q["item_ids"]:
                knowledge.add_encounter(w.store, item, session_id=s.session_id, trigger="check",
                                        context_sentence=q["evidence"][0])
        results.append(outcome)
        s.progress.update(questions=len(results), results=list(results))
    return "completed", {"questions": len(results), "results": results}


# ---------------------------------------------------------------- learner_questions (§3.1: purpose `answer`)


DONE = {"done", "no", "no more", "that's all", "finished", "nothing"}


def _answer_sections(w: World, u: Utterance) -> tuple:
    """What an `answer` call carries: the session's learner context (cached, owner decision 2026-10-24), the
    sentences read in this cycle (book leaves) and the learner's question as said (a non-book leaf that egress
    redacts by content, ADR-0021 E1/E2). One turn: earlier questions are not sent."""
    from leafi.core.ports import Leaf, Section
    from leafi.study.brain import generate, kinds

    page = tuple(Leaf(f"{x.rid}: {x.text}", book=True) for x in kinds.cycle_sentences(w.s))
    return (generate.learner_context(w.s), Section("page", page), Section("question", (Leaf(u.text),)))


async def _answer(w: World, u: Utterance, owner):
    """One `answer` call inside `controls_only` with the filler (D12, D21); None when no backend answered."""
    from leafi.study.brain import call as bc
    from leafi.study.brain import generate, prompts, routing, schemas
    from leafi.study.brain.filler import with_filler

    s, io = w.s, w.inputs
    if s.brain is None:
        return None
    make = prompts.single_request("answer", prompts.ANSWER_SYSTEM, _answer_sections(w, u), schemas.AnswerContent,
                                  learner_id=s.learner_id, session_id=s.session_id)
    ctx = generate.context(s, time.monotonic() + routing.moment_s("answer", s.mouth))
    d = routing.difficulty("answer", question=u.text)
    async with io.controls_only(owner) as taken:
        result = await with_filler(
            bc.brain_call(s.brain, ctx, "answer", make, schemas.AnswerContent.model_validate, d),
            show=io.hub.show, say=io.say if s.mouth == "pc" else None, epoch=s.epoch)
    for item in taken:  # D21 inside an activity: a page turned during the wait is remembered; a skip skips this
        if item.kind == "page" and s.on_page is not None:
            s.on_page(item.u)
        elif item.kind == "skip":
            return None
    return result


async def learner_questions(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    """The learner asks; each answer is one `answer` call grounded in the cycle's read sentences, spoken as a
    non-book line (TTS routes it by content, ADR-0021 E7), a `degraded` one prefaced (D10). Up to `max_turns`
    questions."""
    s, io, cfg = w.s, w.inputs, w.settings
    w.activity_started = time.monotonic()
    answered = asked = 0
    await io.line("questions_intro", owner=("act", aid, "q0"))
    for turn in range(int(act.params.get("max_turns", 5))):
        if w.activity_over():
            break
        owner = ("act", aid, f"q{turn}")
        if turn:
            await io.line("questions_next", owner=owner)
        while True:
            u = await io.listen(cfg.study_idle_s, owner, accepts_page=True)
            s.checkpoint()
            if u is None or not _panel_data(u, controls.of(u)):
                break
            # owner, 2026-10-25: the questions here come from the child; no `answer` call, no turn used
            await io.hub.show(Display("status", phrases.say("questions_child_only")))
        if (late := _late_pages(w, aid)) is not None and s.on_page is not None:
            s.on_page(late)
        if u is None:
            if io.voice:
                break  # no further question
            s.latch.terminate("idle_session")
            return "idle_session", {"questions": asked, "answered": answered}
        if s.take_skip() or (not _panel(u) and " ".join(u.text.lower().strip(" .!?").split()) in DONE):
            break
        ctl = controls.of(u)
        if ctl is not None:
            _store_utterance(w, u, "control")
            if ctl.kind in ("page", "next_page"):
                _page_turn(w, ctl)  # remembered; the next boundary opens it (§3.1 has no `page_turned` here)
                break
            await io.line("noop")
            continue
        if not _confident(u):
            await io.line("questions_again")
            continue
        _store_utterance(w, u, "question")
        asked += 1
        s.progress.update(questions=asked, answered=answered)
        epoch = s.epoch()
        result = await _answer(w, u, owner)
        s.checkpoint()
        if result is None or not phrases.safe(result.value.answer):
            await io.line("questions_unavailable")
            continue
        if result.degraded:
            await io.line("degraded")  # ADR-0017 §5.1: a weaker tier's answer says so
        await io.say(result.value.answer, epoch=epoch)  # D12
        answered += 1
        s.progress.update(questions=asked, answered=answered)
    return "completed", {"questions": asked, "answered": answered}


# ---------------------------------------------------------------- teach_items, recall_items (ADR-0017 §3.1, §3.4)


async def _ask_item(w: World, aid: int, i: int, item: int, key: str, prompt: str, expect: str):
    """One item's question and its score. Returns (outcome, utterance, ended): outcome `success` / `fail` /
    `unavailable` / `known` (the learner said "I know this word": the item is `ignored`, source learner, D17);
    `ended` is the activity's own status when the question ended it (idle, a page turn)."""
    from leafi.study.brain import scoring

    s, io, cfg = w.s, w.inputs, w.settings
    owner = ("act", aid, f"item{i}")  # D21: each item its own prompt
    await io.ask(owner, prompt)
    u = await io.listen(CHECK_ANSWER_S if io.voice else cfg.study_idle_s, owner, accepts_page=True)
    s.checkpoint()
    if (late := _late_pages(w, aid)) is not None and s.on_page is not None:
        s.on_page(late)  # D21: remembered; the next boundary opens it
    if u is None and not io.voice:
        s.latch.terminate("idle_session")
        return "unavailable", None, "idle_session"
    ctl = controls.of(u) if u is not None else None
    if ctl is not None and ctl.kind in ("page", "next_page"):
        _store_utterance(w, u, "control")
        _page_turn(w, ctl)  # like a quiz, these kinds cannot end `page_turned` (§3.1): the next boundary opens it
        return "unavailable", None, "completed"
    if s.take_skip() or u is None:
        return "unavailable", None, None
    if ctl is not None and ctl.kind == "know":
        _store_utterance(w, u, "control")
        try:  # a panel `/know` is the owner's (design D8)
            item_status.record(w.store, s.learner_id, item, "ignore", "owner" if _panel(u) else "learner",
                               tz=cfg.household_tz,
                               known_days=cfg.review_known_interval_days, session_id=s.session_id, activity_id=aid)
        except learner_store.LearnerUnavailable:
            log.info("ignore of a learner being forgotten not recorded")
        await io.line("teach_known")
        return "known", u, None
    _store_utterance(w, u, "answer")
    if expect == "item_used":
        outcome = await scoring.item_used(s, u, key, prompt)
    elif expect == "cloze_word":
        outcome = scoring.cloze_word(u, key, w.word_info)
    else:
        outcome = scoring.item_said(u, key, w.word_info)
    return outcome, u, None


async def _score_item(w: World, aid: int, item: int, key: str, outcome: str, u, sentence: str,
                      explanation: str | None) -> None:
    """§3.4: `success` / `fail` write a retrieval event and an encounter (`teach_ok` / `teach_incorrect`, §8.6)."""
    if outcome == "success":
        await w.inputs.line("check_correct")
    elif outcome == "fail":
        await w.inputs.line("teach_answer", word=key)
    if outcome not in ("success", "fail"):
        return
    _retrieval(w, item, aid, outcome, "typed" if u.typed else "heard_confident")
    knowledge.add_encounter(w.store, item, session_id=w.s.session_id,
                            trigger="teach_ok" if outcome == "success" else "teach_incorrect",
                            context_sentence=sentence, explanation_en=explanation)


async def teach_items(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    """The Brain-written explanation of each item, then its prompt, scored by `expect` (§3.1, §3.4; the content
    was checked at construction, D15)."""
    w.activity_started = time.monotonic()
    results: list[str] = []
    await w.inputs.line("teach_intro", count=len(act.content["items"]))
    for i, t in enumerate(act.content["items"]):
        if w.activity_over():
            break
        await w.inputs.say(t["explanation"])
        outcome, u, ended = await _ask_item(w, aid, i, t["item_id"], t["key"], t["prompt"], t["expect"])
        results.append(outcome)
        if ended:
            return ended, {"items": len(results), "results": results}
        await _score_item(w, aid, t["item_id"], t["key"], outcome, u, t["sentence"], t["explanation"])
        w.s.progress.update(items=len(results), results=list(results))
    return "completed", {"items": len(results), "results": results}


def _cue(w: World, item: int, key: str) -> tuple[str, str, str] | None:
    """`code` content for recall (§3.3): the item's stored explanation (say the word), else its stored sentence with
    the word blanked (fill it in); (prompt, expect, sentence), or None when neither is stored."""
    from leafi.study.brain.kinds import CLOZE

    e = w.store.one("SELECT explanation_en, context_sentence FROM encounters WHERE knowledge_item_id=? AND "
                    "explanation_en IS NOT NULL AND explanation_en != '' ORDER BY id DESC LIMIT 1", (item,))
    if e is not None:
        return phrases.say("recall_meaning", explanation=e["explanation_en"]), "item_said", e["context_sentence"]
    for r in w.store.all("SELECT context_sentence FROM encounters WHERE knowledge_item_id=? AND context_sentence != '' "
                         "ORDER BY id DESC", (item,)):
        ws = words(r["context_sentence"])
        k = [x.lower() for x in words(key)]
        for j in range(len(ws) - len(k) + 1):
            if [x.lower() for x in ws[j:j + len(k)]] == k:
                blanked = " ".join(ws[:j] + [CLOZE] + ws[j + len(k):])
                return phrases.say("recall_cloze", sentence=blanked), "cloze_word", r["context_sentence"]
    return None


async def recall_items(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    """Cued recall of items due by the §6.2 spacing, from their stored explanation (no generation, §3.1)."""
    w.activity_started = time.monotonic()
    marks = ",".join("?" * len(act.params["item_ids"]))
    keys = {r["id"]: r["key"] for r in w.store.all(
        f"SELECT id, key FROM knowledge_items WHERE id IN ({marks}) AND learner_id=?",
        (*act.params["item_ids"], w.s.learner_id))}
    todo = [(i, keys[i], c) for i in act.params["item_ids"] if i in keys and (c := _cue(w, i, keys[i]))]
    results: list[str] = []
    await w.inputs.line("recall_intro", count=len(todo))
    for n, (item, key, (prompt, expect, sentence)) in enumerate(todo):
        if w.activity_over():
            break
        outcome, u, ended = await _ask_item(w, aid, n, item, key, prompt, expect)
        results.append(outcome)
        if ended:
            return ended, {"items": len(results), "results": results}
        await _score_item(w, aid, item, key, outcome, u, sentence, None)
        w.s.progress.update(items=len(results), results=list(results))
    return "completed", {"items": len(results), "results": results}


KINDS = {"read_listen": read_listen, "practise_errors": practise_errors, "review_anki": review_anki,
         "read_aloud": read_aloud, "add_cards": add_cards, "break": break_, "wait": wait, "end": end, "quiz": quiz,
         "learner_questions": learner_questions, "teach_items": teach_items, "recall_items": recall_items}
