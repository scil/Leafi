"""The session loop (ADR-0017 §2; the pseudocode is the rule, this follows it step by step).

Lease first; recovery and the guest sweep; the session starts owned by a fresh guest; inside one cancel scope
with no deadline and one task group (the deadline watcher, the input readers): identify, assign the arm, identify
the book, then boundaries — menu, sequence (the default policy until M7 brings a Brain), negotiate, run — with
continuations after a page turn. `finalize` does local work only; `deliver` and `extract_notes` run shielded with
their own limits; the lease is released whatever happened.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import anyio

from leafi.core import learner_store
from leafi.core import lease as speech_lease
from leafi.core.ports import Counts
from leafi.core.storage import Store, dumps, now_iso
from leafi.privacy import runtime
from leafi.privacy.egress import owner as egress_owner
from leafi.study import books, controls, knowledge, lexicon, records
from leafi.study.harness import busy, guests, policy, rows
from leafi.study.harness import settings as hs
from leafi.study.harness.activities import KINDS
from leafi.study.harness.identify import identify
from leafi.study.harness.inputs import Inputs, StaleInput
from leafi.study.harness.latch import Jump, Latch, Terminal, set_fate
from leafi.study.harness.ledger import Ledger
from leafi.study.harness.menu import allowed
from leafi.study.harness.negotiate import REOBSERVE, negotiate
from leafi.study.harness.state import Activity, Boundary, Session
from leafi.study.harness.status import TERMINAL, ActivityStatus
from leafi.study.harness.world import PageRequest, World

log = logging.getLogger("leafi.harness.loop")

DELIVER_S, EXTRACT_S = 10.0, 20.0


@dataclass
class Env:
    """What a session is built from (the runner fills it from the app's devices and services)."""

    store: Store
    hub: object
    settings: object  # the household Settings
    listener: object | None = None
    control_source: object | None = None
    control_sources: list | None = None  # every typed source beside the main one; None: the Hub's (ADR-0017 §1)
    page_tracker: object | None = None
    ocr: object | None = None
    catalog: object | None = None
    anki: object | None = None
    pron: object | None = None
    word_info: object | None = None
    book_title: str | None = None
    page_text: str | None = None
    page_number: int | None = None
    learner: str | None = None  # `study --learner NAME`
    brain: object | None = None  # M7
    rng: random.Random = field(default_factory=random.Random)
    on_built: object | None = None  # tests: called with (session, world) once built


def assign_arm(s: Session, has_brain: bool, rng: random.Random) -> None:
    """§9: per session, after identification. Without a Brain every session is the default policy's."""
    if s.settings["policy.sequencer"] == "brain" and has_brain:
        share = float(s.settings["policy.explore_share"])
        s.arm = "default" if rng.random() < share else "brain"
        s.propensity = share if s.arm == "default" else 1.0 - share
    else:
        s.arm, s.propensity = "default", 1.0


def set_deadlines(s: Session) -> None:
    """§1 / §6.3: soft = start + session length; hard = soft + grace (`hard` end mode: no grace)."""
    soft = time.monotonic() + 60.0 * s.settings.session_max_min()
    grace = 0 if s.settings["session.end_mode"] == "hard" else int(s.settings["session.grace_min"])
    s.soft_deadline = soft
    s.latch.hard_deadline = soft + 60.0 * grace


def continuation_allowed(s: Session) -> bool:
    return not s.past_soft_deadline() or s.settings["session.end_mode"] == "finish_activity"


async def identify_book(s: Session, w: World, env: Env) -> None:
    io = w.inputs
    title, isbn = env.book_title, None
    if not title and env.ocr is not None and env.hub.eye() is not None:
        guess = await books.identify(env.hub.eye(), env.ocr, env.catalog)
        if guess.title:
            await io.line("confirm_title", title=guess.title, owner=("setup", "confirm_title"))
            u = await io.listen(env.settings.study_idle_s, ("setup", "confirm_title"))
            s.checkpoint()
            ctl = controls.of(u) if u is not None else None
            if ctl is not None and ctl.kind == "yes":
                title, isbn = guess.title, guess.isbn
    while not title:
        await io.line("ask_title", owner=("setup", "title"))
        u = await io.listen(env.settings.study_idle_s, ("setup", "title"))
        s.checkpoint()
        if u is None:
            s.latch.terminate("idle_session")
            s.checkpoint()
        title = u.text.strip() if controls.of(u) is None else None
    w.book_id = books.find_or_create(s.store, title, isbn, language=env.settings.study_language)
    w.book_title = title  # the snapshot's (panel design D3)
    s.store.execute("UPDATE reading_sessions SET book_id=? WHERE id=?", (w.book_id, s.session_id))
    if env.page_text is not None:
        w.pending = PageRequest(env.page_number, env.page_text)
        return
    if env.page_number is not None:
        w.pending = PageRequest(env.page_number, None)
    prev = records.resumable_read(s.store, s.learner_id, w.book_id)
    if prev is None:
        return
    printed = s.store.one("SELECT printed_number FROM pages WHERE id=?", (prev["page_id"],))["printed_number"]
    await io.line("continue_offer", page=printed or prev["page_id"], owner=("setup", "continue"))
    u = await io.listen(env.settings.study_idle_s, ("setup", "continue"))
    s.checkpoint()
    ctl = controls.of(u) if u is not None else None
    if ctl is not None and ctl.kind == "yes":
        w.page_id, w.pending = prev["page_id"], None  # read_listen opens it with range `rest` (§8.5)


def _flush_pending(s: Session) -> None:
    """§7.3: an end status that could not be written is kept in memory and written with the next write."""
    while s.pending_rows:
        aid, status, outcome = s.pending_rows[0]
        rows.finish_activity(s.store, aid, status, outcome, learner_id=s.learner_id)
        s.pending_rows.pop(0)


async def run_activity(s: Session, w: World, act: Activity, *, continuation: bool = False) -> ActivityStatus:
    """Start and finish rows inside; a cancelled activity ends with the latch's mapped status, never `running`;
    a step still busy at its time limit ends the activity `store_busy` (§7.3)."""
    params = dict(act.params) | ({"continuation": True} if continuation else {})
    s.latch.epoch.bump()  # activity start

    def start() -> int:
        _flush_pending(s)
        return rows.start_activity(
            s.store, session_id=s.session_id, kind=act.kind, cycle_id=s.cycle_id, params=params,
            continuation=continuation, arm=s.arm, propensity=s.propensity,
            policy_version=policy.policy_version(policy.order_of(s)), decided_by=act.decided_by,
            override=act.override or s.boundary.override, autonomy=s.autonomy, epoch=s.latch.epoch.turn_id)

    try:
        aid = await busy.retry(start)
    except busy.StoreBusy:
        log.warning("store busy: %s did not start", act.kind)
        return ActivityStatus.STORE_BUSY
    outcome = None
    s.progress = {}
    entry = {"id": aid, "kind": act.kind, "decided_by": act.decided_by, "params": params, "started": time.monotonic(),
             "status": ActivityStatus.RUNNING.value, "outcome": None, "progress": s.progress}  # the snapshot's
    s.log.append(entry)
    s.changed()

    def logged(status) -> None:
        """The end, in memory: the panel-line count joins the outcome on every finish path (panel design D8)."""
        nonlocal outcome
        if s.progress.get("panel_inputs"):
            outcome = dict(outcome or {}) | {"panel_inputs": s.progress["panel_inputs"]}
        entry["status"], entry["outcome"] = ActivityStatus(status).value, outcome
        w.inputs.activity_id = w.inputs.activity_progress = None
        s.changed()

    def finish_now(status) -> ActivityStatus:
        """No awaiting: also used while the scope is being cancelled. Busy → kept for the next write."""
        w.inputs.activity_started_at = None
        logged(status)
        try:
            rows.finish_activity(s.store, aid, status, outcome, learner_id=s.learner_id)
        except sqlite3.OperationalError as e:
            if not busy.is_busy(e):
                raise
            s.pending_rows.append((aid, ActivityStatus(status), outcome))
        s.latch.epoch.bump()  # activity end
        w.first_boundary = False
        return ActivityStatus(status)

    w.inputs.activity_started_at = time.monotonic()  # an Ear switch after this ends the activity (D21)
    w.inputs.activity_id, w.inputs.activity_progress = aid, s.progress
    try:
        status, outcome = await KINDS[act.kind](w, replace(act, params=params), aid)
    except StaleInput:
        return finish_now(ActivityStatus.ABORTED_STALE)
    except Jump:  # a want at a safe point (ADR-0017 §2.1 as amended): the completed steps are kept
        outcome = dict(s.progress) | {"ended_by": "do"}
        return finish_now(ActivityStatus.COMPLETED)
    except (Terminal, anyio.get_cancelled_exc_class()):
        finish_now(s.latch.status())
        raise
    except sqlite3.OperationalError as e:
        if not busy.is_busy(e):
            s.latch.terminate("internal_error")
            finish_now(ActivityStatus.INTERNAL_ERROR)
            raise
        log.warning("store busy inside %s", act.kind)
        return finish_now(ActivityStatus.STORE_BUSY)
    except Exception:
        s.latch.terminate("internal_error")
        finish_now(ActivityStatus.INTERNAL_ERROR)
        raise
    # any other BaseException is a process exit: the row stays `running` for startup recovery (§2, §8.5)
    w.inputs.activity_started_at = None
    if s.latch.want is not None and status == ActivityStatus.COMPLETED:  # ended at its natural step for a want
        outcome = dict(outcome or {}) | {"ended_by": "do"}
    logged(status)
    try:
        await busy.retry(lambda: rows.finish_activity(s.store, aid, status, outcome, learner_id=s.learner_id))
    except busy.StoreBusy:
        s.pending_rows.append((aid, ActivityStatus(status), outcome))
    s.latch.epoch.bump()  # activity end
    w.first_boundary = False
    return ActivityStatus(status)


def finalize(s: Session, w: World, env: Env) -> dict:
    """Local work in one transaction: the open cycle closes, the summary counts, `ended_at`; then the guest
    end-state rule (ADR-0018 §1). A failure leaves the work to startup recovery."""
    store = s.store
    reason = s.latch.terminal or "end"
    _flush_pending(s)
    if s.pending_audit_brain:  # D8: brain_calls rows a busy store kept back
        from leafi.study.brain import call as bc

        while s.pending_audit_brain:
            bc._insert(store, s.pending_audit_brain.pop(0))
    with store.transaction():
        if s.cycle_id is not None:
            rows.close_cycle(store, s.cycle_id, "stop" if reason == "stop" else "wrap")
        w.end_page_read()
        summ = records.summary(store, s.session_id)
        summ.update(end=reason, arm=s.arm, interrupted=False)
        if w.inputs.panel_lines:  # the owner's lines as command and fate (panel design D8)
            summ["panel_lines"] = [{"command": _command(e["line"])} |
                                   {k: e.get(k) for k in ("wall", "activity_id", "fate", "reason")}
                                   for e in w.inputs.panel_lines]
            summ["panel_inputs_boundary"] = w.inputs.boundary_panel_inputs
        store.execute("UPDATE reading_sessions SET ended_at=?, summary=? WHERE id=?",
                      (now_iso(), dumps(summ), s.session_id))
    if learner_store.get(store, s.learner_id)["kind"] == "learner":
        knowledge.recompute_difficulties(store, s.learner_id)
    if w.book_id is not None:
        lexicon.rebuild(store, w.book_id)
    return summ


def _command(line: str) -> str:
    """A panel line as an enum for the summary, which holds counts and enum strings only (written by a raw UPDATE,
    `tests/test_architecture.py::MAINTENANCE_COLUMNS`): `say`, `fix`, `page`, `do <kind>`, `skip`, … never the
    owner's text, whose answers are already stored as `utterances` through the fenced writer."""
    parts = line.strip().lstrip("/").split()
    cmd = parts[0].lower() if parts else ""
    return f"do {parts[1].lower()}" if cmd == "do" and len(parts) > 1 else cmd


async def deliver(s: Session, w: World, env: Env, summ: dict) -> None:
    """The closing line only while the lease is held; the Anki outbox; each step's outcome into the summary."""
    io = w.inputs
    if s.latch.terminal == "lease_lost":
        await io.line("lease_lost")  # shown on Faces only: the lease is gone
        summ["closing_line"] = "skipped"
    else:
        await io.line("idle" if s.latch.terminal == "idle_session" else "bye")
        summ["closing_line"] = "done"
    try:  # the parent's notification: a name (as a surrogate) and counts (M5 design D5)
        await env.hub.notify(Counts(s.learner_id, s.session_id, summ.get("pages", 0), summ.get("tokens_committed", 0),
                                    summ.get("candidates", 0), summ.get("items_learned", 0)))
    except Exception:
        log.warning("notification failed", exc_info=True)
    summ["anki_synced"] = "skipped"
    if env.anki is not None:
        from leafi.study import anki

        try:
            rep = await anki.sync_outbox(s.store, env.anki, env.settings.anki_deck, env.settings.anki_model,
                                         tz=env.settings.household_tz,
                                         known_days=env.settings.review_known_interval_days)
            summ["anki_synced"], summ["anki_pending"] = "done", rep.pending
        except Exception:
            log.warning("anki sync failed; outbox kept", exc_info=True)
            summ["anki_synced"] = "failed"


async def extract_notes(s: Session, w: World, env: Env, summ: dict) -> None:
    """§7.1 post-session learner notes (M7 design D18), skipped for guests and without a Brain."""
    from leafi.study.brain import notes

    await notes.extract_notes(s, w, env, summ, deadline_s=EXTRACT_S - 1.0)


async def run_session(env: Env) -> int:
    store, cfg = env.store, env.settings
    lease = speech_lease.acquire(cfg.lease_path, cfg.lease_ttl_s)  # refused → LeaseHeld to the caller
    inputs = attribution = None
    try:
        rows.recover(store)
        guests.normalise_orphans(store, cfg.guest_keep_days)
        guests.sweep(store)
        # ADR-0021 E9: spoken-line cache folders of forgotten learners and ended guests, before any synthesis
        cache = getattr(cfg, "cache_dir", None)  # a settings object without one sweeps nothing
        records.sweep_tts_cache(store, Path(cache) if cache is not None else None)
        for mouth in env.hub.mouths.values():  # the camera Mouth's leftover copies (ADR-0021 E9)
            clear = getattr(mouth, "clear_stale", None)
            if clear is not None:
                try:
                    clear()
                except Exception:
                    log.warning("mouth cleanup failed", exc_info=True)
        guest = guests.new_guest(store)
        listener = env.listener or env.hub.listener()
        mode = "voice" if getattr(listener, "is_voice", False) else "text"
        sid = learner_store.insert(store, "reading_sessions", guest, started_at=now_iso(), mode=mode,
                                   devices=dumps(sorted(set(env.hub.mouths) | set(env.hub.faces))),
                                   lease_token=lease.token, owner=egress_owner())
        attribution = runtime.attribution.set(runtime.Attribution(guest, sid))  # moved to the learner at adoption
        latch = Latch()
        latch.epoch.session_id, latch.epoch.learner_id = sid, guest
        lst = hs.load(store, guest)
        inputs = Inputs(hub=env.hub, latch=latch, store=store, listener=listener, control_source=env.control_source,
                        control_sources=env.control_sources,
                        page_tracker=env.page_tracker, page_poll_s=cfg.page_poll_s, lease=lease)
        s = Session(store=store, latch=latch, ledger=Ledger(store, sid, lst.limits()), settings=lst, talk=inputs,
                    session_id=sid, learner_id=guest, brain=env.brain)
        w = World(s=s, inputs=inputs, settings=cfg, word_info=env.word_info, anki=env.anki, pron=env.pron,
                  page_tracker=env.page_tracker)
        s.facts_fn = w.facts
        s.on_page = lambda u: _page_request(w, u)  # D21: a page turn heard at a boundary
        latch.versions = lambda: (hs.version(store, s.learner_id), 0)
        latch.on_settings_change = lambda: _reload(s)
        if env.on_built is not None:
            env.on_built(s, w)
        try:
            with anyio.CancelScope() as latch.scope:
                async with anyio.create_task_group() as latch.tg:
                    inputs.start()
                    latch.spawn(latch.deadline_watcher)
                    try:
                        await _body(s, w, env)
                    finally:
                        latch.tg.cancel_scope.cancel()
        except* Terminal:
            pass
        except* Exception as eg:
            log.error("session failed", exc_info=eg)
            latch.terminate("internal_error")
        inputs.accepting = False  # the body is over: a later line has nobody to act on it (panel design D7)
        set_fate(latch.want, "dropped", "stop" if latch.terminal == "stop" else "session_end")
        s.changed()
        inputs.changed()
        try:
            summ = finalize(s, w, env)
        except sqlite3.OperationalError as e:
            if not busy.is_busy(e):
                raise
            log.warning("store busy at finalize: left to startup recovery (ADR-0017 §7.3)")
            summ = None
        for step, limit in ((deliver, DELIVER_S), (extract_notes, EXTRACT_S)):
            try:
                with anyio.move_on_after(limit, shield=True):
                    await step(s, w, env, summ if summ is not None else {"end": latch.terminal or "end"})
            except Exception:
                log.exception("post-session step failed")  # one step's failure never skips the next
        # The session's egress is over: only now may the sweeper or `forget` act on it, and only now is the guest
        # end-state applied (M5 design D5). A busy write leaves both to the next session's recovery.
        try:
            if summ is not None:
                summ["guest"] = guests.finalize_guest(store, sid, cfg.guest_keep_days)
            store.execute("UPDATE reading_sessions SET summary=COALESCE(?, summary), post_done_at=? WHERE id=?",
                          (dumps(summ) if summ is not None else None, now_iso(), sid))
        except sqlite3.OperationalError:
            log.warning("summary not written (store busy)")
        return sid
    finally:
        if inputs is not None:
            await inputs.close()
        if attribution is not None:
            runtime.attribution.reset(attribution)
        lease.release()


def _drain_late(w: World) -> None:
    """D21 (rev 9): at a boundary, a late page turn becomes the pending page; a late skip is dropped, since no
    offer was heard yet (ADR-0017 §2.1: a skip before an offer excludes nothing)."""
    for item in w.inputs.take_late():
        if item.kind == "page":
            _page_request(w, item.u)


def _page_request(w: World, u) -> None:
    """A page turn heard outside an activity (`/page N`, `--text FILE`, or the Eye) becomes the pending page."""
    ctl = controls.of(u)
    text = None
    if ctl is not None and ctl.path is not None:
        try:
            text = Path(ctl.path).read_text(encoding="utf-8")
        except OSError:
            log.warning("page turn: %s could not be read", ctl.path)
    w.pending = PageRequest(ctl.n if ctl is not None else None, text)


def _reload(s: Session) -> None:
    s.settings = hs.load(s.store, s.learner_id)
    s.ledger.limits = s.settings.limits()


async def _body(s: Session, w: World, env: Env) -> None:
    await identify(s, keep_days=env.settings.guest_keep_days, preset=env.learner)
    assign_arm(s, env.brain is not None, env.rng)
    set_deadlines(s)
    await identify_book(s, w, env)
    while True:
        s.checkpoint()
        s.boundary.content.clear()  # M7 D14: a Reobserve discards the boundary's generated content
        _drain_late(w)
        await w.refresh()
        menu = allowed(s)
        s.boundary.menu = frozenset(menu)
        s.changed()  # a boundary: the snapshot shows its menu (panel design D3)
        prop = None  # the default policy's arm: negotiate's default chain decides
        # ADR-0017 §3.3: the Brain proposes (M7 design D10); a pending want is a named choice, so no proposal
        if s.arm == "brain" and env.brain is not None and s.latch.want is None:
            from leafi.study.brain.sequence import REOBSERVE_PAGE, sequence

            chain = [sp.kind for sp in policy.default_chain(s, menu - {"end"})]
            prop = await sequence(s, w, env.brain, menu, chain)
            if prop == REOBSERVE_PAGE:
                continue
        out = await negotiate(s, prop, menu, s.epoch())
        if out is REOBSERVE:
            continue
        act = out.activity
        if act.kind == "end":
            await run_activity(s, w, act)  # record_boundary: the end row
            break
        if s.past_soft_deadline():
            if s.boundary.want_entry is not None:  # a `/do` switched to, then lost to the deadline
                s.boundary.want_entry.update(fate="dropped", reason="soft_deadline")
            break
        last = await run_activity(s, w, act)
        s.previous_boundary_was_wait = act.kind == "wait"
        s.boundary = Boundary()
        while continuation_allowed(s) and s.latch.want is None and (  # a want goes to the boundary
                (last == ActivityStatus.PAGE_TURNED and w.pending is not None)  # §8.2: same cycle, on every turn
                or (last == ActivityStatus.ABORTED_STALE and act.kind == "read_listen")):  # §1: an Ear switch
            page = "next" if last == ActivityStatus.PAGE_TURNED else "current"  # keeps cycle and page read
            last = await run_activity(s, w, Activity("read_listen", {"page": page, "range": "rest"}, "default"),
                                      continuation=True)
        if last in TERMINAL:
            break
