"""Reading-session state machine (flows/reading-session.md draws it; ADR-0013 owns the rules).

States: IDENTIFY_BOOK → FIND_PAGE → (REVIEW_DUE) → READ ⇄ PRACTICE / CORRECT / EXPLAIN / REPOSITION →
CHECK → FIND_PAGE | WRAP. Every state method returns the next state. The session talks to the world only
through the Hub (Faces/Mouths/Listener/Eye/Notifier) and the service objects it is given.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from leafi.core import lease as speech_lease
from leafi.core.hub import Hub, ListeningGate
from leafi.core.ports import Display, Utterance
from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.core.text import typed_utterance, words
from leafi.study import (
    anki,
    books,
    coach,
    controls,
    corrections,
    knowledge,
    lexicon,
    miscues,
    pages,
    phrases,
    records,
)
from leafi.study.alignment import (
    CandidateCreated,
    CandidateWithdrawn,
    LineSkipped,
    ReadingState,
    SentenceReached,
    Unanchored,
    align,
    back,
    complete_sentence,
    open_candidates,
    pause_completes,
    resumed,
    retry_matches,
    settle,
    skip_read,
)
from leafi.study.controls import Control

log = logging.getLogger("leafi.session")

READ, PRACTICE, CHECK, WRAP, FIND_PAGE, REVIEW_DUE = "READ", "PRACTICE", "CHECK", "WRAP", "FIND_PAGE", "REVIEW_DUE"
PRON_CONFIRM_BELOW = 0.5
ANSWER_WORDS = {"yes", "no", "good", "again"}  # spoken one-word answers in CHECK are answers, not commands  # scorer threshold for `confirmed` (only when PRON_AUTO_JUDGE is on)


@dataclass
class PageRequest:
    number: int | None = None
    text: str | None = None


@dataclass
class SessionFlags:
    idle: bool = False
    stopped: bool = False
    transitions: list[str] = field(default_factory=list)


class StudySession:
    def __init__(self, *, store: Store, hub: Hub, settings, brain=None, anki_client: anki.AnkiClient | None = None,
                 listener=None, pron=None, page_tracker=None, ocr=None, catalog=None, control_source=None) -> None:
        self.store = store
        self.ocr = ocr
        self.catalog = catalog
        self.hub = hub
        self.settings = settings
        self.brain = brain
        self.anki = anki_client
        self.pron = pron
        self.page_tracker = page_tracker
        self.listener = listener or hub.listener()
        self.voice = bool(getattr(self.listener, "is_voice", False))
        self.gate = ListeningGate(self.listener)
        # Control dispatch (review 1 #7, #20): the console is read by one persistent task, also during playback.
        if control_source is None:
            if not self.voice:
                control_source = self.listener
            else:
                control_source = next((lis for lis in hub.listeners.values()
                                       if lis is not self.listener and not getattr(lis, "is_voice", False)), None)
        self.control_source = control_source
        self.stopping = False
        self._inbox: list[Utterance] = []
        self._main_task: asyncio.Task | None = None
        self._control_task: asyncio.Task | None = None
        self._page_task: asyncio.Task | None = None
        self._page_open = False
        self.flags = SessionFlags()
        self.session_id: int | None = None
        self.guard: coach.AsyncGuard | None = None
        self.book_id: int | None = None
        self.page_id: int | None = None
        self.rev: pages.Revision | None = None
        self.state: ReadingState | None = None
        self.read_id: int | None = None
        self.seq = 0
        self.unanchored = 0
        self.reposition = False
        self.first_page = True
        self.request = PageRequest()
        self.resume_row = None
        self.lease: speech_lease.Lease | None = None
        self._renew: asyncio.Task | None = None

    # ------------------------------------------------------------ I/O helpers

    async def say(self, text: str, lang: str = "en", slow: bool = False, local_only: bool = False) -> None:
        """`local_only=True` for any line that embeds learner-originated text (security.md egress table).

        While audio plays, the console is still read: `/stop` cancels speech and is routed to the current state
        (settlement → WRAP), `/skip` cuts the current line only, anything else waits for the next listen().
        """
        if not text:
            return
        if self.stopping:  # a /stop is pending: show, do not speak
            await self.hub.show(Display("say", text, lang))
            return
        if self.control_source is None or not self._will_play():
            await self.gate.speak(self.hub, text, lang, slow=slow, local_only=local_only)
            return
        speak = asyncio.create_task(self.gate.speak(self.hub, text, lang, slow=slow, local_only=local_only))
        while not speak.done():
            ctl_task = self._control_read()
            done, _ = await asyncio.wait({speak, ctl_task}, return_when=asyncio.FIRST_COMPLETED)
            if ctl_task in done:
                self._take_control_read(ctl_task)
                u = ctl_task.result()
                if u is not None:
                    await self._during_playback(u)
        await speak

    def _will_play(self) -> bool:
        return self.hub.policy != "none" and bool(self.hub.mouths) and self.hub.synthesizer is not None

    def _control_read(self) -> asyncio.Task:
        if self.control_source is self.listener:
            if self._main_task is None:
                self._main_task = asyncio.create_task(self.listener.next_utterance(None))
            return self._main_task
        if self._control_task is None:
            self._control_task = asyncio.create_task(self.control_source.next_utterance(None))
        return self._control_task

    def _take_control_read(self, task: asyncio.Task) -> None:
        if task is self._main_task:
            self._main_task = None
        if task is self._control_task:
            self._control_task = None

    async def _during_playback(self, u: Utterance) -> None:
        ctl = controls.parse(u.text)
        if ctl is not None and ctl.kind == "stop":
            self.stopping = True
            self._inbox.insert(0, u)
            await self.hub.stop_speaking()
        elif ctl is not None and ctl.kind == "skip":
            await self.hub.skip_current()
        else:
            self._inbox.append(u)

    async def line(self, key: str, local_only: bool = False, **kw: Any) -> None:
        await self.say(phrases.say(key, **kw), local_only=local_only)

    async def listen(self, timeout_s: float | None) -> Utterance | None:
        """Next input from the reading Listener, the console control source, or an Eye page turn.

        Pending reads persist across calls (nothing is cancelled, nothing is lost); console controls win ties.
        """
        await self.hub.show(Display("listening", "listening"))
        if self._inbox:
            return self._inbox.pop(0)
        if self._main_task is None:
            self._main_task = asyncio.create_task(self.listener.next_utterance(timeout_s))
        tasks = {self._main_task: "main"}
        if self.control_source is not None and self.control_source is not self.listener:
            tasks[self._control_read()] = "control"
        if self.page_tracker is not None and self._page_open:
            if self._page_task is None:
                self._page_task = asyncio.create_task(self._watch_page())
            tasks[self._page_task] = "page"
        done, _ = await asyncio.wait(tasks, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            return None
        for kind in ("control", "page", "main"):
            for t in done:
                if tasks[t] == kind:
                    if kind == "page":
                        self._page_task = None
                    else:
                        self._take_control_read(t)
                        if t is self._main_task:
                            self._main_task = None
                    return t.result()
        return None

    async def _watch_page(self) -> Utterance:
        """Poll the Eye; a settled frame that differs from the page being read is a page turn (`/page`)."""
        tracker = self.page_tracker
        while True:
            await asyncio.sleep(self.settings.page_poll_s)
            eye = self.hub.eye()
            frame = await eye.snapshot(None) if eye is not None else None
            if frame is None:
                continue
            if tracker.last is None:
                tracker.last = frame
                continue
            if tracker.changed(frame):
                settled = await tracker.settle()
                if settled is not None and tracker.changed(settled):
                    log.info("page turn seen by the Eye")
                    return typed_utterance("/page", "eye")

    def _cancel_inputs(self) -> None:
        for t in (self._main_task, self._control_task, self._page_task):
            if t is not None and not t.done():
                t.cancel()
        self._main_task = self._control_task = self._page_task = None

    def _store_utterance(self, u: Utterance, kind: str) -> int:
        return self.store.insert(
            "utterances", page_read_id=self.read_id, page_revision_id=self.rev.id if self.rev else None,
            session_id=self.session_id, text=u.text, kind=kind, created_at=now_iso(),
            words=dumps([[w.text, w.start_s, w.end_s, w.conf] for w in u.words]))

    def _save_state(self) -> None:
        if self.read_id is not None and self.state is not None:
            self.store.execute("UPDATE page_reads SET reading_state=? WHERE id=?",
                               (dumps(self.state.to_json()), self.read_id))
        if self.guard and self.state:
            self.guard.update(self.rev.id if self.rev else None, self.state.turn_id)

    def _bump_turn(self) -> None:
        if self.state is not None:
            self.state.turn_id += 1
            self._save_state()

    # ------------------------------------------------------------ lifecycle

    async def run(self, *, book_title: str | None = None, page_text: str | None = None,
                  page_number: int | None = None) -> int:
        # Exclusive ownership first: a rejected launch must not touch the live session (review 1 #2). Once we
        # hold the lease, every other unfinished session belongs to a dead process and is stale.
        self.lease = speech_lease.acquire(self.settings.lease_path, self.settings.lease_ttl_s)
        records.close_stale_sessions(self.store)
        self._renew = asyncio.create_task(self._renew_loop())
        mode = "voice" if self.voice else "text"
        self.session_id = self.store.insert("reading_sessions", started_at=now_iso(), mode=mode,
                                            devices=dumps(sorted(set(self.hub.mouths) | set(self.hub.faces))),
                                            lease_token=self.lease.token)
        self.guard = coach.AsyncGuard(self.session_id)
        self.request = PageRequest(page_number, page_text)
        try:
            await self.line("hello")
            if self.voice:
                await self.line("playback_stop_hint")
            nxt = await self.identify_book(book_title)
            while nxt != WRAP:
                self.flags.transitions.append(nxt)
                log.info("state %s", nxt)
                self._bump_turn()
                nxt = await getattr(self, nxt.lower())()
            self.flags.transitions.append(WRAP)
            await self.wrap()
        finally:
            self._cancel_inputs()
            if self._renew:
                self._renew.cancel()
            if self.lease:
                self.lease.release()
        return self.session_id

    async def _renew_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, self.settings.lease_ttl_s / 3))
            try:
                self.lease.renew()
            except speech_lease.LeaseHeld:
                log.error("speech lease lost")
                return

    # ------------------------------------------------------------ IDENTIFY_BOOK

    async def identify_book(self, title: str | None) -> str:
        isbn = None
        if not title and self.hub.eye() is not None and self.ocr is not None:
            guess = await books.identify(self.hub.eye(), self.ocr, self.catalog)
            if guess.title:
                await self.line("confirm_title", title=guess.title)
                ans = await self._yes_no()
                if ans is None:
                    return WRAP
                if ans:
                    title, isbn = guess.title, guess.isbn
        if not title:
            title = await self._ask_title()
            if title is None:
                return WRAP
        self.book_id = books.find_or_create(self.store, title, isbn, language=self.settings.study_language)
        self.store.execute("UPDATE reading_sessions SET book_id=? WHERE id=?", (self.book_id, self.session_id))
        row = records.resumable_read(self.store, self.book_id)
        if row is not None:
            printed = self.store.one("SELECT printed_number FROM pages WHERE id=?", (row["page_id"],))
            await self.line("continue_offer", page=printed["printed_number"] or row["page_id"])
            ans = await self._yes_no()
            if ans is None:
                return WRAP
            if ans:
                self.resume_row = row
        return FIND_PAGE

    async def _ask_title(self) -> str | None:
        await self.line("ask_title")
        u = await self.listen(self.settings.study_idle_s)
        if u is None or controls.parse(u.text) and controls.parse(u.text).kind == "stop":
            return None
        return u.text.strip() or None

    async def _yes_no(self) -> bool | None:
        u = await self.listen(self.settings.study_idle_s)
        if u is None:
            self.flags.idle = True
            return None
        ctl = controls.parse(u.text)
        if ctl and ctl.kind == "stop":
            self.flags.stopped = True
            return None
        return bool(ctl and ctl.kind == "yes")

    # ------------------------------------------------------------ FIND_PAGE

    async def find_page(self) -> str:
        self._page_open = False  # no page-turn watching while the page itself is being found
        if self._page_task is not None:
            self._page_task.cancel()
            self._page_task = None
        if self.resume_row is not None:
            row, self.resume_row = self.resume_row, None
            self.page_id = row["page_id"]
            self.rev = pages.current_revision(self.store, self.page_id)
            old = ReadingState.from_json(self.rev.text, loads(row["reading_state"]))
            self._start_page_read(resumed(old), attempt=row["attempt"] + 1)
            return await self._after_page_found()
        while True:
            req = self.request
            if req.text is not None:
                self._load_text_page(req.number, req.text)
                self.request = PageRequest()
                return await self._after_page_found()
            if req.number is not None:
                pid = self.store.one("SELECT id FROM pages WHERE book_id=? AND printed_number=?",
                                     (self.book_id, req.number))
                if pid and pages.current_revision(self.store, pid["id"]):
                    self.page_id = pid["id"]
                    self.rev = pages.current_revision(self.store, self.page_id)
                    self._start_page_read(None)
                    self.request = PageRequest()
                    return await self._after_page_found()
            if self.page_tracker is not None:
                found = await self.page_tracker.find(self.book_id, req.number)
                if found.status == "uncertain":  # PAGE_UNCERTAIN: assessment suspended until confirmed
                    self.flags.transitions.append("PAGE_UNCERTAIN")
                    await self.say(found.message)
                    ans = await self._yes_no()
                    if ans is None:
                        return WRAP
                    if ans:
                        found = self.page_tracker.confirm(found, found.page_id)
                    else:
                        await self.say("Which page is it? Type /page N.")
                if found.status == "ready":
                    self.page_id, self.rev = found.page_id, pages.revision(self.store, found.revision_id)
                    self._start_page_read(None)
                    return await self._after_page_found()
                if found.status != "uncertain":
                    await self.say(found.message)
            else:
                await self.line("ask_page_text")
            u = await self.listen(self.settings.study_idle_s)
            if u is None:
                self.flags.idle = True
                return WRAP
            ctl = controls.parse(u.text)
            if ctl and ctl.kind == "stop":
                self.flags.stopped = True
                return WRAP
            if ctl and ctl.kind == "page":
                text = None
                if ctl.path is not None:
                    try:
                        text = Path(ctl.path).read_text(encoding="utf-8")
                    except OSError:
                        await self.say("I couldn't open that file.")
                        continue
                self.request = PageRequest(ctl.n, text)
                continue
            await self.line("noop")

    def _load_text_page(self, number: int | None, text: str) -> None:
        match = pages.match_page(self.store, self.book_id, pages.observations_of(text), number) \
            if number is not None else pages.PageMatch("new", None, 0.0)
        if match.status == "matched":
            self.page_id = match.page_id
        else:
            self.page_id = pages.create_page(self.store, self.book_id, number, pages.observations_of(text))
        rev_id = pages.add_manual_revision(self.store, self.page_id, text)
        self.rev = pages.revision(self.store, rev_id)
        self._start_page_read(None)

    def _start_page_read(self, state: ReadingState | None, attempt: int | None = None) -> None:
        if attempt is None:
            prev = self.store.one("SELECT MAX(attempt) AS a FROM page_reads WHERE page_id=?", (self.page_id,))
            attempt = (prev["a"] or 0) + 1
        st = state or ReadingState.from_text(self.rev.text)
        self.read_id = self.store.insert("page_reads", session_id=self.session_id, page_id=self.page_id,
                                         page_revision_id=self.rev.id, attempt=attempt, started_at=now_iso(),
                                         tokens_expected=st.n)
        st.page_read_id, st.revision_id = self.read_id, self.rev.id
        self.state = st
        self._page_open = True
        self.seq = 0
        self.unanchored = 0
        self.reposition = False
        self._save_state()

    async def _after_page_found(self) -> str:
        printed = self.store.one("SELECT printed_number FROM pages WHERE id=?", (self.page_id,))["printed_number"]
        await self.line("page_ready", page=printed if printed is not None else "")
        if self.first_page:
            self.first_page = False
            return REVIEW_DUE
        return READ

    # ------------------------------------------------------------ REVIEW_DUE

    async def review_due(self) -> str:
        if self.anki is None:
            return READ
        try:
            await anki.reconcile(self.store, self.anki)
            cards = await anki.due_cards(self.store, self.anki, self.settings.anki_deck, self.settings.review_max_cards)
        except (anki.AnkiUnavailable, anki.AnkiError):
            return READ
        if not cards:
            return READ
        await self.line("review_intro", count=len(cards))
        for card in cards:
            await self.line("review_prompt", front=card.front)
            while True:
                u = await self.listen(self.settings.study_idle_s)
                if u is None:
                    self.flags.idle = True
                    return WRAP
                ctl = controls.parse(u.text)
                kind = ctl.kind if ctl else None
                if kind in ("good", "again"):
                    self._store_utterance(u, "answer")
                    await anki.answer(self.store, self.anki, card, 3 if kind == "good" else 1,
                                      self.settings.review_known_interval_days)
                    break
                if kind == "stop":
                    self.flags.stopped = True
                    return WRAP
                if kind == "skip":
                    return READ  # leaves REVIEW_DUE with no record
                await self.line("noop")
        return READ

    # ------------------------------------------------------------ READ

    def _control(self, u: Utterance, *, reading: bool) -> Control | None:
        """Control precedence wins everywhere (ADR-0013 "skip always"); the only reading exception is the
        grammar's own limit: a spoken utterance longer than 6 words is never a control (review 1 #10)."""
        return controls.parse(u.text)

    async def read(self) -> str:
        idle = 0.0
        while True:
            timeout = self.settings.sentence_pause_s if self.voice else self.settings.study_idle_s
            u = await self.listen(timeout)
            if u is None:
                if not self.voice:
                    self.flags.idle = True
                    return WRAP
                idle += timeout
                sid = pause_completes(self.state)
                if sid is not None:
                    nxt = await self._complete(sid, "pause")
                    if nxt == "BACK":
                        continue
                    if nxt:
                        return nxt
                    if self.state.page_complete():
                        return CHECK
                if idle >= self.settings.study_idle_s:
                    self.flags.idle = True
                    return WRAP
                continue
            idle = 0.0
            ctl = self._control(u, reading=True)
            if ctl is not None:
                nxt = await self._read_control(ctl, u)
            else:
                nxt = await self._read_utterance(u)
            if nxt:
                return nxt

    async def _read_control(self, ctl: Control, u: Utterance) -> str | None:
        kind = ctl.kind
        if kind in ("explain", "fix"):
            uid = self._store_utterance(u, "question" if kind == "explain" else "correction")
            if kind == "explain":
                await self.explain(ctl.text)
            else:
                await self.correct(ctl, uid, typed=u.typed)
            self._bump_turn()
            return None
        self._store_utterance(u, "control")
        if kind == "stop":
            await self._depart()
            self.flags.stopped = True
            return WRAP
        if kind in ("page", "next_page"):
            await self._depart()
            if kind == "page":
                text = None
                if ctl.path is not None:
                    try:
                        text = Path(ctl.path).read_text(encoding="utf-8")
                    except OSError:
                        text = None
                self.request = PageRequest(ctl.n, text)
            else:
                cur = self.store.one("SELECT printed_number FROM pages WHERE id=?", (self.page_id,))["printed_number"]
                self.request = PageRequest(cur + 1 if cur is not None else None)
            return FIND_PAGE
        if kind == "back":
            self.state = back(self.state, ctl.n or 1)
            self._save_state()
            return None
        if kind == "skip":
            self.state, sid, cands = skip_read(self.state)
            for i in cands:
                mid = self._miscue_at(i)
                if mid:
                    miscues.set_status(self.store, mid, "unsure", reason="skipped")
            self.state = settle(self.state, cands)
            self._save_state()
            return CHECK if self.state.page_complete() else None
        await self.line("noop")
        return None

    async def _depart(self) -> None:
        """Completion (iii) of the current sentence, then page settlement (stop / next page / page turn)."""
        sid = self.state.current_sentence() if self.state else None
        if sid is not None and sid not in self.state.completed:
            self.state, _ = complete_sentence(self.state, sid)
        if self.read_id is not None:
            miscues.settle_open(self.store, self.read_id, "skipped")
            self.state = settle(self.state, open_candidates(self.state))
            self._save_state()
            self._end_page_read()

    async def _read_utterance(self, u: Utterance) -> str | None:
        if u.typed and not u.words:  # an empty typed line is a line end, never an alignment (review 1 #13)
            sid = pause_completes(self.state) if u.line_end else None
            if sid is not None:
                nxt = await self._complete(sid, "pause")
                if nxt and nxt != "BACK":
                    return nxt
            return CHECK if self.state.page_complete() else None
        self.seq += 1
        uid = self._store_utterance(u, "reading")
        ws = [w.text for w in u.words]
        st, obs, events = align(self.state, ws, self.seq, whole_page=self.reposition)
        if any(isinstance(e, Unanchored) for e in events):
            if self.reposition:
                return None
            self.unanchored += 1
            if self.unanchored < 2:
                return None
            st, obs, events = align(self.state, ws, self.seq, whole_page=True)
            if any(isinstance(e, Unanchored) for e in events):
                self.reposition = True
                await self.line("reposition")
                return None
        self.unanchored = 0
        self.reposition = False
        self._persist(uid, obs, events, st)
        if any(isinstance(e, LineSkipped) for e in events):
            await self.line("line_skipped")
        reached = [e.sentence_id for e in events if isinstance(e, SentenceReached)]
        for sid in reached:
            if sid in self.state.completed:
                continue
            nxt = await self._complete(sid, "reached")
            if nxt == "BACK":
                return None
            if nxt:
                return nxt
        if not reached and u.typed and u.line_end:
            sid = pause_completes(self.state)
            if sid is not None:
                nxt = await self._complete(sid, "pause")
                if nxt == "BACK":
                    return None
                if nxt:
                    return nxt
        return CHECK if self.state.page_complete() else None

    def _persist(self, uid: int, obs, events, st: ReadingState) -> None:
        with self.store.transaction():
            obs_ids = [self.store.insert("observations", utterance_id=uid, kind=o.kind, token_start=o.token_start,
                                         token_end=o.token_end, heard_text=o.heard, sim=o.sim,
                                         created_at=now_iso()) for o in obs]
            for e in events:
                if isinstance(e, CandidateCreated):
                    tok = st.tokens[e.token_index]
                    tok.miscue_id = miscues.create(
                        self.store, observation_id=obs_ids[e.observation_index], page_read_id=self.read_id,
                        revision_id=self.rev.id, expected=e.expected, token_index=e.token_index,
                        char_span=tok.span, heard=e.heard)
                elif isinstance(e, CandidateWithdrawn):
                    mid = st.tokens[e.token_index].miscue_id
                    if mid:
                        miscues.set_status(self.store, mid, "withdrawn", reason=e.reason)
            self.state = st
            self._save_state()

    async def _complete(self, sid: int, trigger: str) -> str | None:
        self.state, cands = complete_sentence(self.state, sid)
        self._save_state()
        if cands:
            nxt = await self.practice(cands)
            if nxt:
                return nxt
        else:
            await self.line("sentence_done")
        return None

    # ------------------------------------------------------------ PRACTICE (ADR-0013 → Practice)

    async def practice(self, cands: list[int]) -> str | None:
        self.flags.transitions.append(PRACTICE)
        items = [(i, self.state.tokens[i].text) for i in cands]
        plan, rest = coach.practice_plan(self.store, items)
        for i, _ in rest:
            mid = self._miscue_at(i)
            if mid:
                miscues.set_status(self.store, mid, "unsure", reason="not_practised")
            self.state = settle(self.state, [i])
        self._save_state()
        for i, word in plan:
            mid = self._miscue_at(i)
            if mid is None:
                self.state = settle(self.state, [i])
                continue
            nxt = await self._practise_word(mid, word)
            if nxt in (WRAP, FIND_PAGE):
                return nxt
            if nxt == "BACK":
                return "BACK"
            self.state = settle(self.state, [i])
            self._save_state()
        return None

    async def _practise_word(self, mid: int, word: str) -> str | None:
        await self.line("practice_intro", word=word)
        await self.say(word, slow=True)
        attempt = 0
        while attempt < 2:
            await self.line("practice_retry" if attempt == 0 else "practice_again", word=word)
            if attempt:
                await self.say(word, slow=True)
            u = await self.listen(self.settings.practice_retry_s if self.voice else None)
            if u is None:
                miscues.set_status(self.store, mid, "unsure", reason="idle")
                await self.line("practice_idle")
                return None
            ctl = controls.parse(u.text)
            if ctl is not None:
                self._store_utterance(u, "control")
                if ctl.kind == "stop":
                    await self._depart()
                    self.flags.stopped = True
                    return WRAP
                if ctl.kind in ("page", "next_page"):
                    self.request = PageRequest(ctl.n) if ctl.kind == "page" else PageRequest()
                    await self._depart()
                    return FIND_PAGE
                if ctl.kind == "skip":
                    miscues.record_practice(self.store, mid, attempt + 1, "skipped")
                    miscues.set_status(self.store, mid, "unsure", reason="skipped")
                    await self.line("practice_unsure")
                    return None
                if ctl.kind == "back":
                    miscues.set_status(self.store, mid, "unsure", reason="skipped")
                    self.state = settle(self.state, [self._token_of(mid)])
                    self.state = back(self.state, ctl.n or 1)
                    self._save_state()
                    return "BACK"
                await self.line("noop")
                continue
            attempt += 1
            self._store_utterance(u, "practice")
            evidence, score = await self._score(u, word)
            matched = retry_matches([w.text for w in u.words], word)
            miscues.record_practice(self.store, mid, attempt, "matched" if matched else "disagreed", evidence)
            if u.audio_ref is not None:
                u.audio_ref.release()
            if matched:
                miscues.set_status(self.store, mid, "withdrawn", reason="practice", evidence=evidence)
                await self.line("practice_withdrawn")
                return None
            if attempt == 2:
                if evidence == "acoustic" and score is not None and score < PRON_CONFIRM_BELOW:
                    miscues.set_status(self.store, mid, "confirmed", evidence="acoustic", score=score)
                    item = knowledge.upsert_item(self.store, "pronunciation", word)
                    knowledge.add_encounter(self.store, item, session_id=self.session_id, trigger="miscue",
                                            revision_id=self.rev.id, context_sentence=self._sentence_of_token(mid))
                else:
                    miscues.set_status(self.store, mid, "unsure", reason="disagreed", evidence=evidence, score=score)
                await self.line("practice_unsure")
        return None

    async def _score(self, u: Utterance, word: str) -> tuple[str, float | None]:
        if not (self.settings.pron_auto_judge and u.audio_ref is not None and self.pron is not None):
            return "none", None
        try:
            result = await self.pron.score(u.audio_ref, word)
        except Exception:
            log.warning("pronunciation scorer failed", exc_info=True)
            return "none", None
        return ("acoustic", result.score) if result is not None else ("none", None)

    def _miscue_at(self, i: int) -> int | None:
        """The open candidate at token i of the current state (by stable reference, not by index)."""
        mid = self.state.tokens[i].miscue_id
        if mid is None:
            return None
        row = self.store.one("SELECT status FROM miscues WHERE id=?", (mid,))
        return mid if row and row["status"] == "candidate" else None

    def _token_of(self, mid: int) -> int:
        return next(i for i, t in enumerate(self.state.tokens) if t.miscue_id == mid)

    def _sentence_of_token(self, mid: int) -> str:
        i = self._token_of(mid)
        return coach.sentence_text(self.rev.text, self.state, self.state.tokens[i].sentence_id)

    # ------------------------------------------------------------ EXPLAIN / CORRECT

    def _window_sids(self) -> list[int]:
        cur = self.state.current_sentence() or (self.state.sentence_ids() or [1])[-1]
        return [s for s in (cur - 1, cur, cur + 1) if s in self.state.sentence_ids()]

    async def explain(self, target_text: str | None) -> None:
        self.flags.transitions.append("EXPLAIN")
        target = coach.find_on_page(self.state, target_text) if target_text else None
        cur = self.state.current_sentence() or (self.state.sentence_ids() or [1])[-1]
        sentence = coach.sentence_text(self.rev.text, self.state, cur) if self.state.n else ""
        await self.line("explain_wait", target=target or "this sentence")
        window = coach.page_window(self.rev.text, self.state, self._window_sids())
        data = None
        if self.brain is not None and window:
            req = coach.explain_request(window, target, self.settings.redact_list())
            data = await coach.enrich(self.brain, req, self.guard, self.settings.brain_deadline_s)
        kind = "word" if target and " " not in target else "phrase"
        item = knowledge.upsert_item(self.store, kind, target or sentence)
        if data:
            await self.say(phrases.safe_or(data["meaning_en"], "explain_unavailable"))
            if data.get("meaning_zh"):
                await self.say(data["meaning_zh"], "zh")
            if data.get("example") and phrases.safe(data["example"]):
                await self.say(data["example"])
        else:
            await self.line("explain_unavailable")
        knowledge.add_encounter(self.store, item, session_id=self.session_id, trigger="explain",
                                revision_id=self.rev.id, context_sentence=sentence,
                                explanation_en=data["meaning_en"] if data else None,
                                explanation_zh=(data.get("meaning_zh") or None) if data else None,
                                example=(data.get("example") or None) if data else None)

    async def correct(self, ctl: Control, utterance_id: int, typed: bool) -> None:
        self.flags.transitions.append("CORRECT")
        if not ctl.old or not ctl.text:
            await self.line("noop")
            return
        text = self.rev.text
        st = self.state
        near = st.tokens[min(st.pcur, st.n - 1)].start if st.n else 0
        m = max(1, len(words(ctl.old)))
        lo = max(0, st.ccur - 6, st.sentence_start(st.ccur)) if st.ccur < st.n else max(0, st.n - 12)
        hi = min(st.n, st.pcur + math.ceil(1.5 * m) + 8)
        window = (st.tokens[lo].start, st.tokens[hi - 1].end) if st.n and hi > lo else None
        span = corrections.locate(text, ctl.old, near, window) or corrections.locate(text, ctl.old, near)
        source = "text" if typed else "voice"
        if span is None:
            await self.line("correction_not_found", local_only=True, old=ctl.old)
            corrections.record_unlocated(self.store, revision_id=self.rev.id, old_text=ctl.old, new_text=ctl.text,
                                         source=source, utterance_id=utterance_id)
            await self.line("correction_saved")
            return
        res = corrections.apply_correction(self.store, page_id=self.page_id, revision_id=self.rev.id,
                                           char_start=span[0], char_end=span[1], new_text=ctl.text, source=source,
                                           utterance_id=utterance_id, state=self.state, book_id=self.book_id)
        self.rev = pages.revision(self.store, res.revision_id)
        self.state = res.state
        self._save_state()
        await self.line("correction_thanks", local_only=True, new=ctl.text)

    # ------------------------------------------------------------ CHECK (ADR-0013 → CHECK outcomes)

    async def check(self) -> str:
        window = coach.page_window(self.rev.text, self.state, sorted(self.state.completed))
        data = None
        if self.brain is not None and window:
            req = coach.questions_request(window, self.settings.redact_list())
            data = await coach.enrich(self.brain, req, self.guard, self.settings.brain_deadline_s)
        if data:
            await self.line("check_intro")
            leave = False
            for q in data["questions"]:
                await self.say(q["question"])
                while True:  # every control is dispatched before anything is graded (review 1 #5)
                    u = await self.listen(self.settings.check_answer_s if self.voice else None)
                    ctl = controls.parse(u.text) if u is not None else None
                    if ctl is None or ctl.kind == "dont_know" or (not ctl.typed and ctl.kind in ANSWER_WORDS):
                        break
                    if ctl.kind == "stop":
                        self.flags.stopped = True
                        return WRAP
                    if ctl.kind in ("page", "next_page"):
                        self.request = PageRequest(ctl.n)
                        return FIND_PAGE
                    if ctl.kind == "back":
                        self.state = back(self.state, ctl.n or 1)
                        self._save_state()
                        return READ
                    if ctl.kind == "skip":
                        leave = True  # leaves CHECK with no record
                        break
                    await self.line("noop")
                if leave:
                    break
                if u is not None:
                    self._store_utterance(u, "answer")
                skipped = bool(ctl and ctl.kind == "dont_know")
                outcome = coach.check_outcome(u.text if u is not None else None, q["keywords"], skipped=skipped)
                if outcome == "correct":
                    await self.line("check_correct")
                await self.say(phrases.safe_or(q["answer"], "check_correct"))
                if outcome == "incorrect":
                    key = coach.find_on_page(self.state, q["item_key"]) or q["item_key"]
                    item = knowledge.upsert_item(self.store, "fact", key)
                    knowledge.add_encounter(self.store, item, session_id=self.session_id, trigger="check",
                                            revision_id=self.rev.id, context_sentence=window)
        await self.line("after_check")
        while True:
            u = await self.listen(self.settings.study_idle_s)
            if u is None:
                self.flags.idle = True
                return WRAP
            ctl = controls.parse(u.text)
            kind = ctl.kind if ctl else None
            if kind == "stop":
                self.flags.stopped = True
                return WRAP
            if kind in ("page", "next_page"):
                self._end_page_read()
                text = None
                if ctl.path is not None:
                    try:
                        text = Path(ctl.path).read_text(encoding="utf-8")
                    except OSError:
                        text = None
                if kind == "next_page":
                    cur = self.store.one("SELECT printed_number FROM pages WHERE id=?",
                                         (self.page_id,))["printed_number"]
                    self.request = PageRequest(cur + 1 if cur is not None else None)
                else:
                    self.request = PageRequest(ctl.n, text)
                return FIND_PAGE
            if kind == "back":
                self.state = back(self.state, ctl.n or 1)
                self._save_state()
                return READ
            await self.line("noop")

    # ------------------------------------------------------------ WRAP

    def _end_page_read(self) -> None:
        if self.read_id is None or self.state is None:
            return
        st = self.state
        counts = {s: sum(1 for t in st.tokens if t.status == s) for s in ("committed", "settled", "unread")}
        self.store.execute(
            "UPDATE page_reads SET ended_at=COALESCE(ended_at, ?), tokens_committed=?, tokens_matched=?, "
            "tokens_unread=?, reading_state=? WHERE id=?",
            (now_iso(), counts["committed"] + counts["settled"], counts["committed"], counts["unread"],
             dumps(st.to_json()), self.read_id))

    async def wrap(self) -> None:
        if self.read_id is not None:
            if miscues.open_for_read(self.store, self.read_id):
                miscues.settle_open(self.store, self.read_id, "skipped")
                self.state = settle(self.state, open_candidates(self.state))
            self._end_page_read()
        knowledge.recompute_difficulties(self.store)
        if self.book_id is not None:
            lexicon.rebuild(self.store, self.book_id)
        summ = records.summary(self.store, self.session_id)
        summ.update(idle=self.flags.idle, stopped=self.flags.stopped, interrupted=False)
        if self.anki is not None:
            try:
                rep = await anki.sync_outbox(self.store, self.anki, self.settings.anki_deck, self.settings.anki_model)
                summ["anki_pending"] = rep.pending
            except Exception:
                log.warning("anki sync failed; outbox kept", exc_info=True)
        self.store.execute("UPDATE reading_sessions SET ended_at=?, summary=? WHERE id=?",
                           (now_iso(), dumps(summ), self.session_id))
        await self.line("idle" if self.flags.idle else "bye")
        await self.hub.notify("Leafi: reading done",
                              f"pages {summ['pages']}, words read {summ['tokens_committed']}, "
                              f"words to practise {summ['candidates']}, new items {summ['items_learned']}")
