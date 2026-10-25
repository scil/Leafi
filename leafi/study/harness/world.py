"""What the activities share (ADR-0017 §3.1): the session state, the inputs, the store, the devices, and the page
read being worked on. `facts()` computes `state.Facts` for the menu and the default policy; `open_page_read` is
ADR-0013 → Opening a page read on the database."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.core.wordinfo import NullWordInfo, WordInfo
from leafi.study import controls, knowledge, pages
from leafi.study.alignment import ReadingState, Status, opened
from leafi.study.harness import rows
from leafi.study.harness.inputs import Inputs
from leafi.study.harness.state import Facts, Session

log = logging.getLogger("leafi.harness.world")


@dataclass
class PageRequest:
    number: int | None = None
    text: str | None = None


def reading_counts(st: ReadingState) -> dict[str, int]:
    """Tokens by ADR-0013 status (every status, zero when absent): the page read's counts and the snapshot's."""
    counts = dict.fromkeys(get_args(Status), 0)
    for t in st.tokens:
        counts[t.status] = counts.get(t.status, 0) + 1
    return counts


class World:
    def __init__(self, *, s: Session, inputs: Inputs, settings, book_id: int | None = None,
                 word_info: WordInfo | None = None, anki=None, pron=None, page_tracker=None,
                 page_request: PageRequest | None = None) -> None:
        self.s, self.inputs, self.settings = s, inputs, settings
        self.store: Store = s.store
        self.book_id = book_id
        self.word_info = word_info or NullWordInfo()
        self.anki, self.pron, self.page_tracker = anki, pron, page_tracker
        self.pending: PageRequest | None = page_request  # the page the learner turned to or typed
        self.page_id: int | None = None
        self.printed: int | None = None  # the page's printed number, for the snapshot (panel design D3)
        self.book_title: str | None = None
        self.rev: pages.Revision | None = None
        self.state: ReadingState | None = None
        self.read_id: int | None = None
        self.seq = 0
        self.first_boundary = True
        self.anki_due = 0
        self.anki_reachable = False
        self.cards_observed = False
        self.activity_started = time.monotonic()

    # ---- facts (refresh() before each boundary: Anki is asynchronous, facts() is not)
    async def refresh(self) -> None:
        self.anki_reachable, self.anki_due = False, 0
        if self.anki is None:
            return
        from leafi.study import anki

        cfg = self.settings
        try:
            await anki.reconcile(self.store, self.anki, cfg.review_known_interval_days, tz=cfg.household_tz)
            if not self.cards_observed:  # once per session, when Anki is reachable (M7 design D17)
                await anki.observe_cards(self.store, self.anki, self.s.learner_id, tz=cfg.household_tz,
                                         known_days=cfg.review_known_interval_days)
                self.cards_observed = True
            cards = await anki.due_cards(self.store, self.anki, self.s.learner_id, cfg.anki_deck, 20)
        except (anki.AnkiUnavailable, anki.AnkiError):
            return
        self.anki_reachable, self.anki_due = True, len(cards)

    def facts(self, s: Session | None = None) -> Facts:
        s = s or self.s
        cyc = s.cycle_id
        return Facts(
            first_boundary=self.first_boundary, anki_reachable=self.anki_reachable, anki_due=self.anki_due,
            has_book=self.book_id is not None,
            unread_current=self.state is not None and not self.state.page_complete(),
            can_acquire_next_page=self.book_id is not None,  # the page tracker, a typed page, or asking for one
            familiar_pages=bool(self._familiar_page()),
            open_candidates=tuple(self.ordered_candidates(cyc)) if cyc else (),
            read_sentences=bool(cyc) and self._cycle_read_sentences(cyc),
            cardable_items=tuple(self.cardable_items()),
            new_item_candidates=tuple(self.new_items(s)) if cyc else (),
            recall_due=tuple(self.recall_due(s)),
        )

    def new_items(self, s: Session) -> list[int]:
        """Ranked new-item candidates from the open cycle's read sentences (ADR-0017 §6.2), at most what the
        cycle's new-item budget has left (R11: the menu offers `teach_items` from these)."""
        from leafi.study import items
        from leafi.study.brain import kinds  # lazy: the brain package imports the harness state

        left = s.ledger.cycle_new_left(s.cycle_id)
        return items.new_candidates(self.store, s.learner_id, [x.text for x in kinds.cycle_sentences(s)],
                                    self.word_info, left) if left > 0 else []

    def recall_due(self, s: Session) -> list[int]:
        from leafi.study import item_status

        cfg = self.settings
        return item_status.recall_due(self.store, s.learner_id, item_status.household_day(cfg.household_tz),
                                      cfg.review_known_interval_days)

    def _cycle_read_sentences(self, cycle_id: int) -> bool:
        return any(loads(r["reading_state"], {}).get("completed") for r in self.store.all(
            "SELECT reading_state FROM page_reads WHERE cycle_id=? AND reading_state IS NOT NULL", (cycle_id,)))

    def ordered_candidates(self, cycle_id: int) -> list[int]:
        """Open candidates of the cycle, by the learner's Difficulty weight (high first), then position."""
        rows_ = self.store.all("SELECT id, expected, page_read_id, expected_token_index FROM miscues "
                               "WHERE cycle_id=? AND status='candidate'", (cycle_id,))
        w = knowledge.word_weights(self.store, self.s.learner_id)
        from leafi.core.text import norm

        rows_.sort(key=lambda r: (-w.get(norm(r["expected"]), 0.0), r["page_read_id"], r["expected_token_index"]))
        return [r["id"] for r in rows_]

    def cardable_items(self) -> list[int]:
        """Items of this learner explained in this session (a stored explanation and context sentence, `code`
        content owner) with no card yet."""
        return [r["id"] for r in self.store.all(
            "SELECT DISTINCT k.id FROM knowledge_items k JOIN encounters e ON e.knowledge_item_id = k.id "
            "WHERE k.learner_id=? AND e.session_id=? AND e.explanation_en IS NOT NULL AND e.context_sentence != '' "
            "AND NOT EXISTS (SELECT 1 FROM anki_outbox o WHERE o.knowledge_item_id = k.id AND o.front IS NOT NULL) "
            "ORDER BY k.id", (self.s.learner_id, self.s.session_id))]

    def _familiar_page(self) -> int | None:
        if self.book_id is None:
            return None
        row = self.store.one(
            "SELECT pr.page_id FROM page_reads pr JOIN reading_sessions s ON s.id = pr.session_id JOIN pages p ON "
            "p.id = pr.page_id WHERE s.learner_id=? AND p.book_id=? AND pr.page_id IS NOT ? ORDER BY pr.id DESC "
            "LIMIT 1", (self.s.learner_id, self.book_id, self.page_id))
        return row["page_id"] if row else None

    # ---- page acquisition
    def _load_text(self, number: int | None, text: str) -> int:
        match = pages.match_page(self.store, self.book_id, pages.observations_of(text), number) \
            if number is not None else pages.PageMatch("new", None, 0.0)
        pid = match.page_id if match.status == "matched" else \
            pages.create_page(self.store, self.book_id, number, pages.observations_of(text))
        pages.add_manual_revision(self.store, pid, text)
        return pid

    async def _from_request(self, req: PageRequest) -> int | None:
        if req.text is not None:
            return self._load_text(req.number, req.text)
        if req.number is not None:
            row = self.store.one("SELECT id FROM pages WHERE book_id=? AND printed_number=?", (self.book_id, req.number))
            if row and pages.current_revision(self.store, row["id"]):
                return row["id"]
        if self.page_tracker is not None:
            found = await self.page_tracker.find(self.book_id, req.number)
            if found.status == "uncertain":
                await self.inputs.ask(("world", "confirm_page"), found.message)
                u = await self.inputs.listen(self.settings.study_idle_s, ("world", "confirm_page"), accepts_page=True)
                ctl = controls.of(u) if u is not None else None
                if ctl is not None and ctl.kind == "page" and self.s.on_page is not None:
                    self.s.on_page(u)  # another page named instead of a yes: acquire that one (D21)
                    return None
                if ctl is not None and ctl.kind == "yes":
                    found = self.page_tracker.confirm(found, found.page_id)
            if found.status == "ready":
                return found.page_id
            if found.status != "uncertain":
                await self.inputs.say(found.message)
        return None

    async def acquire_page(self, which: str) -> int | None:
        """The page for `next` or `familiar`: a pending request (page turn, typed text), the Eye, or asking.
        None when the learner gave none before `study_idle_s`."""
        if which == "familiar":
            return self._familiar_page()
        if self.pending is None and self.page_id is not None:
            cur = self.store.one("SELECT printed_number FROM pages WHERE id=?", (self.page_id,))["printed_number"]
            self.pending = PageRequest(cur + 1 if cur is not None else None)
        while True:
            req, self.pending = self.pending or PageRequest(), None
            pid = await self._from_request(req)
            if pid is not None:
                return pid
            if self.pending is not None:
                continue
            owner = ("world", "page_text")
            if self.page_tracker is None:
                await self.inputs.line("ask_page_text", owner=owner)
            u = await self.inputs.listen(self.settings.study_idle_s, owner, accepts_page=True)
            if u is None:
                return None
            ctl = controls.of(u)
            if ctl is not None and ctl.kind == "page":
                text = None
                if ctl.path is not None:
                    try:
                        text = Path(ctl.path).read_text(encoding="utf-8")
                    except OSError:
                        await self.inputs.say("I couldn't open that file.")
                        continue
                self.pending = PageRequest(ctl.n, text)
                continue
            await self.inputs.line("noop")

    # ---- page reads (ADR-0013 → Opening a page read)
    def _touched_since(self, page_id: int, from_rev: int, to_rev: int) -> list[tuple[int, int]]:
        """Spans on `to_rev` that a correction after `from_rev` wrote."""
        out = []
        for r in pages.chain(self.store, page_id):
            if from_rev < r.rev <= to_rev and r.source == "correction":
                for _os, _oe, ns, ne in r.edit_map:
                    out.append(pages.map_to_revision(self.store, page_id, (ns, ne), r.rev, to_rev))
        return out

    def open_page_read(self, page_id: int, rng="rest", familiar: bool = False) -> bool:
        """Set the current page read; True when it is new. Same cycle and page: resumed as it is."""
        cyc = self.s.cycle_id
        rev = pages.current_revision(self.store, page_id)
        same = self.store.one("SELECT id, reading_state FROM page_reads WHERE cycle_id=? AND page_id=? "
                              "ORDER BY id DESC LIMIT 1", (cyc, page_id)) if cyc else None
        self.page_id, self.rev = page_id, rev
        self.printed = self.store.one("SELECT printed_number FROM pages WHERE id=?", (page_id,))["printed_number"]
        if same is not None and same["reading_state"]:
            self.read_id = same["id"]
            self.state = ReadingState.from_json(rev.text, loads(same["reading_state"]))
            return False
        fresh = ReadingState.from_text(rev.text)
        if isinstance(rng, dict) or familiar:
            start = fresh.first_index(rng["from"]) if isinstance(rng, dict) else 0
            st = opened(fresh, None, range_from=start)
        else:
            prev = self.store.one(
                "SELECT pr.reading_state, rv.text, rv.rev FROM page_reads pr JOIN reading_sessions s ON s.id = "
                "pr.session_id JOIN page_revisions rv ON rv.id = pr.page_revision_id WHERE s.learner_id=? AND "
                "pr.page_id=? AND pr.reading_state IS NOT NULL ORDER BY pr.id DESC LIMIT 1",
                (self.s.learner_id, page_id))
            if prev is None:
                st = opened(fresh, None)
            else:
                old = ReadingState.from_json(prev["text"], loads(prev["reading_state"]))
                if old.ccur >= old.n:
                    c = fresh.n  # the page was finished: the range is empty
                else:
                    pos = old.tokens[old.ccur].start
                    pos = pages.map_to_revision(self.store, page_id, (pos, pos), prev["rev"], rev.rev)[0]
                    c = next((i for i, t in enumerate(fresh.tokens) if t.start >= pos), fresh.n)
                spans = self._touched_since(page_id, prev["rev"], rev.rev)
                touched = {i for i, t in enumerate(fresh.tokens) if any(pages.overlaps(t.span, sp) for sp in spans)}
                st = opened(fresh, c, touched)
        prev_attempt = self.store.one("SELECT MAX(attempt) AS a FROM page_reads WHERE page_id=?", (page_id,))["a"]
        self.read_id = self.store.insert("page_reads", session_id=self.s.session_id, cycle_id=cyc, page_id=page_id,
                                         page_revision_id=rev.id, attempt=(prev_attempt or 0) + 1,
                                         started_at=now_iso(), tokens_expected=st.n)
        st.page_read_id, st.revision_id = self.read_id, rev.id
        self.state, self.seq = st, 0
        self.save_state()
        e = self.s.latch.epoch
        e.page_read_id, e.revision_id = self.read_id, rev.id
        e.bump()
        return True

    def save_state(self) -> None:
        if self.read_id is not None and self.state is not None:
            self.store.execute("UPDATE page_reads SET reading_state=? WHERE id=?",
                               (dumps(self.state.to_json()), self.read_id))

    def end_page_read(self) -> None:
        if self.read_id is None or self.state is None:
            return
        st = self.state
        counts = reading_counts(st)
        self.store.execute(
            "UPDATE page_reads SET ended_at=?, tokens_committed=?, tokens_matched=?, tokens_unread=?, "
            "unaligned_words=?, reading_state=? WHERE id=?",
            (now_iso(), counts["committed"] + counts["settled"], counts["committed"], counts["unread"],
             st.unaligned_words, dumps(st.to_json()), self.read_id))

    def ensure_cycle(self, activity_id: int) -> int:
        """A boundary-chosen reading activity opens a cycle (closing the previous one: `next_reading`)."""
        if self.s.cycle_id is not None:
            rows.close_cycle(self.store, self.s.cycle_id, "next_reading")
        self.s.cycle_id = rows.open_cycle(self.store, self.s.session_id, activity_id)
        self.store.execute("UPDATE activities SET cycle_id=? WHERE id=?", (self.s.cycle_id, activity_id))
        self.s.latch.epoch.cycle_id = self.s.cycle_id
        return self.s.cycle_id

    def activity_over(self) -> bool:
        """`limits.activity_max_min`, or a pending want (ADR-0017 §2.1 as amended 2026-10-25): the activity ends
        `completed` at its next natural step, before it asks its next question."""
        if self.s.latch.want is not None:
            return True
        return time.monotonic() - self.activity_started >= 60.0 * self.s.settings["limits.activity_max_min"]
