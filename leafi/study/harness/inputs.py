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

import logging
import math

import anyio

from leafi.core import alerts
from leafi.core import lease as speech_lease
from leafi.core.hub import Hub, ListeningGate
from leafi.core.ports import Display, ListenerLost, Utterance
from leafi.core.text import typed_utterance
from leafi.study import controls, phrases
from leafi.study.harness.latch import Latch

log = logging.getLogger("leafi.harness.inputs")

EYE_OFFLINE_AFTER = 10  # consecutive empty page-watch frames before "camera offline" is shown (TD-20)
_TIMEOUT = object()      # a source's own timeout (a scripted None): listen() returns None
_SWITCHED = object()     # the Ear was lost and the console took over


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

    # ---- readers
    async def _reader(self, name: str) -> None:
        while True:
            await self._want[name].wait()
            self._want[name] = anyio.Event()
            self._busy[name] = True
            try:
                u = await self._sources[name].next_utterance(None)
            except ListenerLost as e:
                self._busy[name] = False
                if name == "main":
                    await self._listener_lost(e)
                    return
                raise
            self._busy[name] = False
            await self._deliver(u, name)

    async def _deliver(self, u: Utterance | None, name: str) -> None:
        if u is None:
            if name == "main" or self._console_is_main:
                await self._send.send(_TIMEOUT)
            return
        ctl = controls.parse(u.text)
        if ctl is not None and ctl.kind == "stop":
            await self.hub.stop_speaking()
            self.latch.terminate("stop")
            return
        if ctl is not None and ctl.kind == "skip":
            if self.speaking:
                await self.hub.skip_current()  # during playback skip cuts the current line only
                return
            self.latch.post_skip()
        await self._send.send(u)

    async def _listener_lost(self, err: BaseException) -> None:
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
        await self._send.send(_SWITCHED)

    # ---- listen / say
    async def listen(self, timeout_s: float | None) -> Utterance | None:
        """Next input, or None at `timeout_s` (None waits). Raises StaleInput after an Ear switch."""
        await self.hub.show(Display("listening", "listening"))
        for name in self._sources:
            self._request(name)
        with anyio.move_on_after(math.inf if timeout_s is None else timeout_s):
            item = await self._recv.receive()
            if item is _TIMEOUT:
                return None
            if item is _SWITCHED:
                await self.say(phrases.say("mic_lost"))
                raise StaleInput("listener switched to the console")
            return item
        return None

    def lease_held(self) -> bool:
        return self.latch.terminal != "lease_lost"

    async def say(self, text: str, lang: str = "en", *, slow: bool = False, local_only: bool = False) -> None:
        """`local_only=True` for any line that embeds learner-originated text (security.md egress table). Controls
        are read during playback; nothing is spoken after the lease is lost (Faces still show it)."""
        if not text:
            return
        if not self.lease_held():  # after `stop` the closing line is still spoken (deliver, §2); never after this
            await self.hub.show(Display("say", text, lang))
            return
        self.speaking = True
        if self.control_source is not None:
            self._request("control" if "control" in self._sources else "main")
        try:
            await self.gate.speak(self.hub, text, lang, slow=slow, local_only=local_only)
        finally:
            self.speaking = False

    async def line(self, key: str, local_only: bool = False, **kw) -> None:
        await self.say(phrases.say(key, **kw), local_only=local_only)

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
                    await self._send.send(typed_utterance("/page", "eye"))

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
