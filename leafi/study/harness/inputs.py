"""Inputs and speech on the session's anyio task group (ADR-0017 §1; replaces v1 `StudySession.listen/say`).

Every reader runs as a child spawned through the latch, so cancelling the session cancels it; nothing calls a raw
`task.cancel()`. Readers are demand-driven: a source is read only while a `listen()` or a `say()` wants input,
one read at a time, and a read left pending when the caller gave up stays pending and delivers to the next
caller (nothing is lost, nothing is read ahead). Controls act at once, also during playback:

- `stop` sets the latch (`terminate("stop")`), which cancels the scope and with it any speech;
- `skip` cuts the current line while Leafi speaks, otherwise it goes into the skip queue (`take_skip`);
- a page turn (`/page`, "next page", or a settled Eye frame) is delivered as an utterance for the activity;
- a lost lease silences every Mouth and sets `lease_lost`; nothing is spoken after it;
- a lost Ear switches to the console (text mode) with the epoch bumped and the running activity ended
  `aborted_stale` (`StaleInput`), or sets `listener_lost_no_console` when there is no console.
"""

from __future__ import annotations

import contextlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import anyio

from leafi.core import alerts
from leafi.core import lease as speech_lease
from leafi.core.hub import Hub, ListeningGate
from leafi.core.ports import SYSTEM, Display, ListenerLost, Provenance, Utterance
from leafi.core.text import typed_utterance
from leafi.study import controls, phrases
from leafi.study.harness.latch import Latch

log = logging.getLogger("leafi.harness.inputs")

EYE_OFFLINE_AFTER = 10  # consecutive empty page-watch frames before "camera offline" is shown (TD-20)
OWNER_KEEP_S = 60.0     # the owner timeline keeps this long, plus its newest entry before the cutoff (D21)
_UNOWNED = object()     # listen() without an owner: M6's behaviour, every item taken


@dataclass(frozen=True)
class _Item:
    """What a reader delivered (M7 design D21): `utterance`, `skip`, `page` or `timeout`, with the prompt that was
    current when the learner finished it (None: no prompt was current)."""

    kind: str
    u: Utterance | None
    owner: object


@dataclass(frozen=True)
class _Switched:
    """The Ear was lost at `at` (monotonic) and the console took over."""

    at: float


class StaleInput(Exception):
    """The input source changed under the running activity: it ends `aborted_stale` (ADR-0017 §1)."""


class Inputs:
    def __init__(self, *, hub: Hub, latch: Latch, store, listener, control_source=None, page_tracker=None,
                 page_poll_s: float = 1.0, lease: speech_lease.Lease | None = None) -> None:
        self.hub, self.latch, self.store = hub, latch, store
        self.listener = listener
        self.voice = bool(getattr(listener, "is_voice", False))
        if control_source is None:
            control_source = listener if not self.voice else next(
                (lis for lis in hub.listeners.values() if lis is not listener and not getattr(lis, "is_voice", False)),
                None)
        self.control_source = control_source
        self.gate = ListeningGate(listener)
        self.page_tracker, self.page_poll_s = page_tracker, page_poll_s
        self.lease = lease
        self.page_open = False   # the page watcher reports turns only while a reading activity wants them
        self.speaking = False
        self.eye_misses = 0
        self._send, self._recv = anyio.create_memory_object_stream[object](math.inf)
        self._want: dict[str, anyio.Event] = {}
        self._busy: dict[str, bool] = {}
        self._sources: dict[str, object] = {}
        self._console_is_main = False  # after a lost Ear (text mode)
        self._owners: list[tuple[float, object]] = []  # D21: (since, prompt id) timeline
        self.late: list[_Item] = []  # pages and skips of ended prompts (D21)
        self.activity_started_at: float | None = None  # set by run_activity while an activity runs
        self.notice: str | None = None  # a phrase the main flow says before its next line ("mic_lost")
        self._waiting = 0  # depth of controls_only()

    # ---- lifecycle
    def start(self) -> None:
        """Spawn the readers, the page watcher and the lease watcher into the session's task group."""
        self._add("main", self.listener)
        if self.control_source is not None and self.control_source is not self.listener:
            self._add("control", self.control_source)
        if self.page_tracker is not None:
            self.latch.spawn(self._watch_page)
        if self.lease is not None:
            self.latch.spawn(self._renew_lease)

    def _add(self, name: str, source) -> None:
        self._sources[name] = source
        self._want[name] = anyio.Event()
        self._busy[name] = False
        self.latch.spawn(self._reader, name)

    def _request(self, name: str) -> None:
        if name in self._want and not self._busy[name]:
            self._want[name].set()

    # ---- ownership (M7 design D21): an input belongs to the prompt current when the learner finished it
    def present(self, owner) -> None:
        """`owner` (a prompt id, or None) is current from now: called before a prompt is spoken or shown."""
        if not self._owners or self._owners[-1][1] != owner:
            now = time.monotonic()
            self._owners.append((now, owner))
            cutoff = now - OWNER_KEEP_S  # prune, but keep the newest entry at or before the cutoff
            while len(self._owners) > 1 and self._owners[1][0] <= cutoff:
                self._owners.pop(0)

    def owner_at(self, t: float):
        owner = None
        for since, o in self._owners:
            if since > t:
                break
            owner = o
        return owner

    @property
    def current_owner(self):
        return self._owners[-1][1] if self._owners else None

    def take_late(self, match: Callable[[object], bool] | None = None) -> list[_Item]:
        """Pages and skips whose prompt had ended when they arrived (D21): drained by the boundary (all of them) or
        by the running activity (`match`: its own prompts'; the others stay for the next boundary)."""
        if match is None:
            late, self.late = self.late, []
            return late
        late = [i for i in self.late if match(i.owner)]
        self.late = [i for i in self.late if not match(i.owner)]
        return late

    # ---- readers
    async def _reader(self, name: str) -> None:
        while True:
            await self._want[name].wait()
            self._want[name] = anyio.Event()
            self._busy[name] = True
            asked = time.monotonic()
            try:
                u = await self._sources[name].next_utterance(None)
            except ListenerLost as e:
                self._busy[name] = False
                if name == "main":
                    self._listener_lost(e)
                    return
                raise
            self._busy[name] = False
            await self._deliver(u, name, asked)

    async def _deliver(self, u: Utterance | None, name: str, asked: float) -> None:
        if u is None:
            if name == "main" or self._console_is_main:  # as M6: only the main source's silence is a timeout
                await self._send.send(_Item("timeout", None, self.owner_at(asked)))
            return
        owner = self.owner_at(u.ended_at if u.ended_at is not None else time.monotonic())
        ctl = controls.parse(u.text)
        if ctl is not None and ctl.kind == "stop":
            await self.hub.stop_speaking()
            self.latch.terminate("stop")
            return
        if ctl is not None and ctl.kind == "skip":
            if self.speaking and owner == self.current_owner:
                await self.hub.skip_current()  # during playback skip cuts the current line only
                return
            await self._send.send(_Item("skip", u, owner))  # posted when its listener takes it (D21)
            return
        kind = "page" if ctl is not None and ctl.kind == "page" else "utterance"
        await self._send.send(_Item(kind, u, owner))

    def _listener_lost(self, err: BaseException) -> None:
        """Synchronous, before any await (D21 rev 8/9): the console becomes the main source and `Switched` is in
        the stream before any line the console delivers next; "mic lost" is said by the main flow's next line."""
        log.error("voice listener lost: %s", err)
        alerts.insert(self.store, "study-mic", "event", "mic_lost")  # a code: `err` names the device (ADR-0016)
        console = self.control_source if self.control_source is not None and \
            not getattr(self.control_source, "is_voice", False) else None
        if console is None:
            self.latch.terminate("listener_lost_no_console")
            return
        self.listener, self.voice, self.gate = console, False, ListeningGate(console)
        self.control_source = console
        del self._sources["main"]  # this reader ends; the console reader now delivers the main input
        self._console_is_main = True
        self.latch.epoch.bump()
        self.notice = "mic_lost"
        self._send.send_nowait(_Switched(time.monotonic()))

    # ---- listen / say
    async def listen(self, timeout_s: float | None, owner=_UNOWNED, *, accepts_page: bool = True
                     ) -> Utterance | None:
        """Next input, or None at `timeout_s` (None waits). Returns what M6's callers received: an utterance (a
        skip is posted to the skip queue and returned; a page turn comes back as its `/page …` utterance).

        `owner` (M7 design D21): the prompt this listen answers. Unowned (the default) behaves as M6 and takes
        every item. An owned listen takes only items of its prompt (or of no prompt), parks a page or skip of an
        ended prompt in `late`, drops other stale items, and ignores a page unless `accepts_page`. An Ear switch
        raises StaleInput when an activity began before it, for a setup prompt, or for an unowned listen; at a
        boundary it is absorbed (the epoch bump makes the boundary re-observe)."""
        owned = owner is not _UNOWNED
        if owned:
            self.present(owner)
        await self.hub.show(Display("listening", "listening"))
        if self._recv.statistics().current_buffer_used == 0:  # an input already waiting answers first (as M6)
            for name in self._sources:
                self._request(name)
        with anyio.move_on_after(math.inf if timeout_s is None else timeout_s):
            while True:
                item = await self._recv.receive()
                if isinstance(item, _Switched):
                    started = self.activity_started_at
                    setup = isinstance(owner, tuple) and owner[:1] == ("setup",)
                    if not owned or setup or (started is not None and started < item.at):
                        raise StaleInput("listener switched to the console")
                    continue
                if owned and item.owner is not None and item.owner != owner:
                    if item.kind in ("page", "skip"):
                        self.late.append(item)  # D21: routed to the boundary or the activity, not lost
                    else:
                        log.info("stale input dropped (prompt %s, listening for %s)", item.owner, owner)
                    for name in self._sources:  # a source freed by the stale read is asked again (D21)
                        self._request(name)
                    continue
                if item.kind == "timeout":
                    return None
                if item.kind == "skip":
                    self.latch.post_skip()
                    return item.u
                if item.kind == "page" and not accepts_page:
                    log.info("page turn ignored by a listen that does not take pages")
                    continue
                return item.u
        return None

    async def ask(self, owner, text: str, lang: str = "en", *, provenance: Provenance = SYSTEM, **kw) -> None:
        """A prompt (D21): `owner` is current from before its first word, so an answer typed while it plays is
        its answer."""
        self.present(owner)
        await self._speak(text, lang, provenance=provenance, **kw)

    @contextlib.asynccontextmanager
    async def controls_only(self, owner):
        """Around a Brain wait (D21): the readers stay asked so `stop` and `skip` act during the call; on exit the
        caller gets the pages and skips of `owner` (it decides what they mean) and everything else stays queued."""
        self.present(owner)
        self._waiting += 1
        taken: list[_Item] = []
        async with anyio.create_task_group() as tg:
            async def keep_asking():
                while True:
                    for name in self._sources:
                        self._request(name)
                    await anyio.sleep(0.05)

            tg.start_soon(keep_asking)
            try:
                yield taken
            finally:
                tg.cancel_scope.cancel()
                self._waiting -= 1
                rest = []
                while True:
                    try:
                        item = self._recv.receive_nowait()
                    except anyio.WouldBlock:
                        break
                    if isinstance(item, _Item) and item.kind in ("page", "skip") and item.owner == owner:
                        taken.append(item)
                    else:
                        rest.append(item)
                for item in rest:
                    self._send.send_nowait(item)

    def lease_held(self) -> bool:
        return self.latch.terminal != "lease_lost"

    async def say(self, text: str, lang: str = "en", *, slow: bool = False, provenance: Provenance = SYSTEM) -> None:
        """`provenance` says where the text came from (M5 design D13): a learner's own words, page text, or Leafi's
        own phrase; the TTS service keeps a learner's words (and any line holding a protected name) off the
        cloud. Controls are read during playback; nothing is spoken after the lease is lost (Faces still show
        it). A plain line is no prompt (D21): outside a Brain wait it makes no prompt current, so a line typed
        while it plays goes to the next listen, as in M6."""
        if self._waiting == 0:
            self.present(None)
        await self._speak(text, lang, slow=slow, provenance=provenance)

    async def _speak(self, text: str, lang: str = "en", *, slow: bool = False, provenance: Provenance = SYSTEM) -> None:
        if self.notice is not None:  # "mic lost", deferred from the Ear's reader to the main flow (D21)
            notice, self.notice = self.notice, None
            await self._speak(phrases.say(notice))
        if not text:
            return
        if not self.lease_held():  # after `stop` the closing line is still spoken (deliver, §2); never after this
            await self.hub.show(Display("say", text, lang))
            return
        self.speaking = True
        if self.control_source is not None and self._will_play():  # controls are read only while audio plays
            self._request("control" if "control" in self._sources else "main")
        try:
            await self.gate.speak(self.hub, text, lang, slow=slow, provenance=provenance)
        finally:
            self.speaking = False

    def _will_play(self) -> bool:
        return self.hub.policy != "none" and bool(self.hub.mouths) and self.hub.synthesizer is not None

    async def line(self, key: str, *, provenance: Provenance = SYSTEM, owner=_UNOWNED, **kw) -> None:
        """A phrase; `provenance` is that of the most restrictive value filled into it (`system` for counts).
        With `owner` the phrase is a prompt (`ask`, D21)."""
        text = phrases.say(key, **kw)
        if owner is _UNOWNED:
            await self.say(text, provenance=provenance)
        else:
            await self.ask(owner, text, provenance=provenance)

    # ---- watchers
    async def _watch_page(self) -> None:
        tracker = self.page_tracker
        while True:
            await anyio.sleep(self.page_poll_s)
            if not self.page_open:
                continue
            eye = self.hub.eye()
            frame = await eye.snapshot(None) if eye is not None else None
            if frame is None:
                self.eye_misses += 1
                if self.eye_misses == EYE_OFFLINE_AFTER:
                    log.warning("Eye returned no frame for %d polls; camera offline?", self.eye_misses)
                    await self.hub.show(Display("status", phrases.say("eye_offline")))
                continue
            self.eye_misses = 0
            if tracker.last is None:
                tracker.last = frame
                continue
            if tracker.changed(frame):
                settled = await tracker.settle()
                if settled is not None and tracker.changed(settled):
                    log.info("page turn seen by the Eye")
                    await self._send.send(_Item("page", typed_utterance("/page", "eye"),
                                                self.owner_at(time.monotonic())))

    async def _renew_lease(self) -> None:
        """Renew every third of the TTL; a failed renewal means another launch took the lease (TD-15)."""
        while True:
            await anyio.sleep(max(0.1, self.lease.ttl_s / 3))
            try:
                self.lease.renew()
            except speech_lease.LeaseHeld:
                log.error("speech lease lost: another Leafi session took it over; stopping")
                await self.hub.stop_speaking()
                alerts.insert(self.store, "study-lease", "event", "lease_lost")  # after silencing (ADR-0016)
                self.latch.terminate("lease_lost")
                return

    async def close(self) -> None:
        close = getattr(self.listener, "close", None)
        if close is not None:
            await close()
