"""The `code`-owned activities (ADR-0017 §3.1; ADR-0013 owns the reading and practice rules).

Each runs as `await KINDS[kind](world, activity, activity_id) -> (status, outcome)`. Cancellation (the latch) and
`StaleInput` pass through to the loop's `run_activity`, which maps them to a status; an activity returns only
its own statuses. Nothing is practised inside reading and nothing is said there beyond §6.1.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import time

from leafi.core import learner_store
from leafi.core.ports import Display, Provenance, Utterance
from leafi.core.storage import dumps, loads, now_iso
from leafi.core.text import words
from leafi.study import cards, coach, controls, corrections, knowledge, miscues, pages
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
PAGE = Provenance("page")  # practice words and read-aloud sentences come from the page (M5 design D13)

PRON_CONFIRM_BELOW = 0.5  # scorer threshold for `confirmed` (only when PRON_AUTO_JUDGE is on)
ANSWER_MIN_CONF = 0.8     # §3.4: a spoken answer counts only when every word is at least this confident
EASES = {"again": 1, "hard": 2, "good": 3, "easy": 4}
OUTCOME_OF = {"pass": "matched", "fail": "disagreed", "unclear": "unclear"}


def _store_utterance(w: World, u: Utterance, kind: str) -> int:
    return learner_store.insert_named(  # fenced: it names the learner (M7 design D22)
        w.store, "utterances", page_read_id=w.read_id, page_revision_id=w.rev.id if w.rev else None,
        session_id=w.s.session_id, text=u.text, kind=kind, created_at=now_iso(),
        words=dumps([[x.text, x.start_s, x.end_s, x.conf] for x in u.words]),
        provenance_class="learner", source_learners=dumps([w.s.learner_id]))


def _confident(u: Utterance) -> bool:
    return u.typed or all(x.conf is not None and x.conf >= ANSWER_MIN_CONF for x in u.words)


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


async def _announce(w: World) -> None:
    printed = w.store.one("SELECT printed_number FROM pages WHERE id=?", (w.page_id,))["printed_number"]
    await w.inputs.line("page_ready" if w.inputs.voice else "page_ready_text", page=printed if printed else "")


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


async def _correct(w: World, ctl: controls.Control, uid: int, typed: bool) -> None:
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
    source = "text" if typed else "voice"
    if span is None:
        await w.inputs.line("correction_not_found", provenance=Provenance("learner", (w.s.learner_id,)), old=ctl.old)
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
    await w.inputs.line("correction_thanks", provenance=Provenance("learner", (w.s.learner_id,)), new=ctl.text)


async def _offer_hint(w: World) -> None:
    """§6.1 `stuck_only`: "Want a hint?"; on yes Leafi says the word and the token becomes `supplied`."""
    st = w.state
    if st.pcur >= st.n:
        return
    await w.inputs.line("hint_offer")
    u = await w.inputs.listen(float(w.s.settings["negotiation.ask_s"]))
    w.s.checkpoint()
    ctl = controls.parse(u.text) if u is not None else None
    if ctl is None or ctl.kind != "yes":
        return
    i = st.pcur
    await w.inputs.line("hint_word", word=st.tokens[i].text)
    w.seq += 1
    uid = _store_utterance(w, u, "control")
    new, events = supply(st, i, w.seq)
    _persist(w, uid, [], events, new)
    _complete_reached(w, events)


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
    await _announce(w)
    target = _range_sids(w.state, act.params.get("range", "rest"))
    before = set(w.state.completed)
    interrupt = s.settings["reading.interrupt"]
    back_s, prompt_s = s.settings["reading.silence_backchannel_s"], s.settings["reading.silence_prompt_s"]
    encouraged = False
    io.page_open = True

    def outcome() -> dict:
        return {"page_read_id": w.read_id, "sentences": len(w.state.completed - before)}

    try:
        idle, cued, hinted = 0.0, False, None
        while True:
            if set(target) <= w.state.completed:
                if (w.state.page_complete() and not encouraged and s.settings["reading.encourage"] != "none"
                        and _self_corrections(w)):
                    await io.line("encourage")  # page end: at most one (§6.1)
                    encouraged = True
                return "completed", outcome()
            timeout = cfg.sentence_pause_s if io.voice else cfg.study_idle_s
            u = await io.listen(timeout)
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
                    await _offer_hint(w)
                if idle >= cfg.study_idle_s:
                    s.latch.terminate("idle_session")
                    return "idle_session", outcome()
                continue
            idle, cued = 0.0, False
            if s.take_skip():  # skip completes the current sentence (§3.1)
                w.state, _sid, _ = skip_read(w.state)
                w.save_state()
                continue
            ctl = controls.parse(u.text)
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
                    await _correct(w, ctl, uid, u.typed)
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
            await io.line("practice_intro", provenance=PAGE, word=word)
            await io.say(word, slow=True, provenance=PAGE)
        while attempt < 2:
            await io.line("practice_retry" if attempt == 0 else "practice_again", provenance=PAGE, word=word)
            if attempt:
                await io.say(word, slow=True, provenance=PAGE)
            u = await io.listen(cfg.practice_retry_s if io.voice else None)
            s.checkpoint()
            if u is None:
                miscues.record_practice(w.store, mid, attempt + 1, "idle")
                break
            if s.take_skip():
                miscues.record_practice(w.store, mid, attempt + 1, "skipped")
                break
            ctl = controls.parse(u.text)
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
        await io.line("practice_withdrawn" if final.startswith("withdrawn") else
                      "practice_idle" if final.endswith("idle") else "practice_unsure")
    return "completed", {"practised": done}


# ---------------------------------------------------------------- review_anki (ADR-0004; eases 1-4)


def _retrieval(w: World, item_id: int | None, aid: int, outcome: str, evidence: str) -> None:
    if item_id is None:
        return
    learner_store.insert(w.store, "retrieval_events", w.s.learner_id, item_id=item_id, activity_id=aid,
                         at=now_iso(), day=dt.date.today().isoformat(), outcome=outcome, evidence=evidence)


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
    for card in cards:
        if w.activity_over():
            break
        # a card's text may hold the learner's own words; its provenance is not known here: `learner` (M5 D13)
        await io.line("review_prompt_eases", provenance=Provenance("learner", (s.learner_id,)), front=card.front)
        while True:
            u = await io.listen(cfg.study_idle_s)
            s.checkpoint()
            if u is None:
                s.latch.terminate("idle_session")
                return "idle_session", {"cards": answered}
            if s.take_skip():  # skips the current card
                break
            ctl = controls.parse(u.text)
            kind = ctl.kind if ctl else None
            if kind in EASES:
                _store_utterance(w, u, "answer")
                ease = EASES[kind]
                await anki.answer(w.store, w.anki, s.learner_id, card, ease, cfg.review_known_interval_days)
                if _confident(u):  # §3.4: an unconfident spoken answer writes no retrieval event
                    _retrieval(w, card.knowledge_item_id, aid, "fail" if ease == 1 else "success",
                               "typed" if u.typed else "heard_confident")
                answered += 1
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
    await io.line("read_aloud_intro")
    said = 0
    for sid in sids:
        if w.activity_over():
            break
        text = coach.sentence_text(w.rev.text, st, sid)
        await io.hub.show(Display("say", text))
        await io.say(text, provenance=PAGE)
        s.checkpoint()
        s.take_skip()  # a skip cut this sentence; the next one follows
        said += 1
    return "completed", {"sentences": said, "page_read_id": w.read_id}


async def _pause(w: World, seconds: float, line: str, *, any_input_ends: bool) -> str:
    s, io = w.s, w.inputs
    await io.line(line, seconds=int(seconds))
    await io.hub.show(Display("status", f"{int(seconds)} s"))
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        u = await io.listen(left)
        s.checkpoint()
        if s.take_skip():
            return "skipped"
        if u is None or any_input_ends:
            break
    return "completed"


async def break_(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    return await _pause(w, float(act.params.get("seconds", 60)), "break_start", any_input_ends=False), {}


async def wait(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    """A harness-internal break of `negotiation.wait_s`: any input ends it, so the learner can choose."""
    return await _pause(w, float(act.params.get("seconds", 30)), "wait_start", any_input_ends=True), {}


async def end(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    return "completed", {}  # the closing line is `deliver`'s (§2)


# ---------------------------------------------------------------- add_cards (§7.2: the one path into Anki)


async def add_cards(w: World, act: Activity, aid: int) -> tuple[str, dict]:
    s = w.s
    added, flagged, rejected = [], [], {}
    for item_id in act.params["item_ids"]:
        fields, sentence, prov = cards.stored_text(w.store, item_id)
        verdict, reason = cards.check(w.store, s.learner_id, item_id, fields, sentence)
        if verdict == "reject":
            rejected[item_id] = reason
            continue
        cls, src = learner_store.prov(prov.cls, prov.sources)  # what the card copies (M7 design D15)
        learner_store.insert(w.store, "anki_outbox", s.learner_id, sources=[s.learner_id], knowledge_item_id=item_id,
                             op="add", state="pending", updated_at=now_iso(), front=fields["正面"],
                             back=fields["背面"], sentence=sentence, card_provenance_class=cls,
                             card_source_learners=src)
        added.append(item_id)
        if verdict == "flag":
            flagged.append(item_id)
    if added:
        await w.inputs.line("cards_added", count=len(added))
    return "completed", {"cards": len(added), "flagged": flagged, "rejected": rejected}


KINDS = {"read_listen": read_listen, "practise_errors": practise_errors, "review_anki": review_anki,
         "read_aloud": read_aloud, "add_cards": add_cards, "break": break_, "wait": wait, "end": end}
