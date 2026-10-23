"""Who is studying (ADR-0018 §1), the minimal form of plan M6.5: by name or a console pick, without recognition
(M8). Identification utterances are used in memory and never stored. Confirmation is durable before it is
adopted: one conditional transaction re-keys the session, deletes the empty guest row and bumps the epoch."""

from __future__ import annotations

import logging
import re

from rapidfuzz import fuzz

from leafi.core import learner_store
from leafi.core.ports import Utterance
from leafi.study import controls
from leafi.study.harness import guests
from leafi.study.harness import settings as hs
from leafi.study.harness.inputs import StaleInput
from leafi.study.harness.state import Session

log = logging.getLogger("leafi.harness.identify")

ASK_S = 8.0
MATCH_AT = 85  # fuzzy ≥ 0.85 (ADR-0018 §1)
DECLINE = "\x00declined"
_PREFIX = re.compile(r"^(?:hi|hello|hey)?[ ,]*(?:i'm|i am|im|my name is|it's|it is|this is|me)\s+", re.IGNORECASE)
_DECLINE = re.compile(r"^(?:don'?t|do not) remember me$", re.IGNORECASE)


def parse_name(u: Utterance | None, enrolled: list) -> str | None:
    """A name, a console pick (a number from the list), DECLINE, or None."""
    if u is None or not u.text.strip():
        return None
    text = " ".join(u.text.strip(" .!?").split())
    if _DECLINE.match(text.replace("’", "'")):
        return DECLINE
    if text.isdigit():
        i = int(text) - 1
        return enrolled[i]["display_name"] if 0 <= i < len(enrolled) else None
    if controls.parse(text) is not None:
        return None
    name = _PREFIX.sub("", text)
    if not name or len(name.split()) > 3:
        return None
    return name[:1].upper() + name[1:]


def match(name: str, enrolled: list):
    scored = sorted(((fuzz.ratio(name.casefold(), r["display_name"].casefold()), r) for r in enrolled),
                    key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] >= MATCH_AT else None


def adopt(s: Session, learner_id: int) -> bool:
    """The durable confirmation: true only when the transaction committed."""
    store = s.store
    guest = s.learner_id
    try:
        with store.transaction():
            moved = store.execute(
                "UPDATE reading_sessions SET learner_id=? WHERE id=? AND EXISTS(SELECT 1 FROM learners WHERE id=? "
                "AND kind='learner' AND forgetting=0)", (learner_id, s.session_id, learner_id)).rowcount
            if not moved:
                return False
            if guest != learner_id:
                store.execute("DELETE FROM learners WHERE id=? AND kind='guest' AND NOT EXISTS(SELECT 1 FROM "
                              "reading_sessions WHERE learner_id=?)", (guest, guest))
    except Exception:  # busy: "let's try that again"
        log.warning("adopt failed", exc_info=True)
        return False
    s.learner_id = learner_id
    s.settings = hs.load(store, learner_id)
    s.ledger.limits = s.settings.limits()
    e = s.latch.epoch
    e.learner_id, e.learner_settings_version = learner_id, s.settings.version
    e.bump()
    return True


async def _confirm(s: Session, question: str) -> bool:
    await s.talk.say(question)
    u = await s.talk.listen(ASK_S)
    s.checkpoint()
    ctl = controls.parse(u.text) if u is not None else None
    return ctl is not None and ctl.kind == "yes"


async def identify(s: Session, *, keep_days: int, preset: str | None = None) -> int:
    """Returns the learner id the session now belongs to (possibly the guest)."""
    store = s.store
    if preset is not None:  # `study --learner NAME`: the household chose at launch (plan M3 decision)
        lid, _ = learner_store.choose(store, preset)
        if adopt(s, lid):
            return lid
    while True:
        try:
            return await _identify(s, keep_days)
        except StaleInput:  # the Ear was lost: restart on the console list
            continue


async def _identify(s: Session, keep_days: int) -> int:
    store, talk = s.store, s.talk
    enrolled = learner_store.enrolled(store)
    voice = bool(getattr(talk, "voice", False))
    if enrolled and not voice:
        picks = ", ".join(f"{i}. {r['display_name']}" for i, r in enumerate(enrolled, 1))
        await talk.say(f"Hello! Who's reading today? {picks} - or type your name.")
    else:
        await talk.say("Hello! Who's reading today?")
    name = parse_name(await talk.listen(ASK_S), enrolled)
    s.checkpoint()
    for _attempt in (1, 2):
        if name is None:
            await talk.say("What's your name?")
            name = parse_name(await talk.listen(ASK_S), enrolled)
            s.checkpoint()
        if name == DECLINE:
            guests.set_guest(store, s.learner_id, "declined")
            return s.learner_id
        if name is not None:
            known = match(name, enrolled)
            if known is not None:
                if await _confirm(s, f"{known['display_name']}?") and adopt(s, known["id"]):
                    return known["id"]
            elif await _confirm(s, f"Shall I remember you as {name}?"):
                lid = learner_store.create(store, name)
                if adopt(s, lid):
                    return lid
                await talk.say("Let's try that again.")
        name = None
    days = keep_days
    await talk.say(f"Today will be kept for {days} days, then forgotten." if days else "Today won't be kept.")
    start = store.one("SELECT started_at FROM reading_sessions WHERE id=?", (s.session_id,))["started_at"]
    guests.set_guest(store, s.learner_id, "unconfirmed", guests.expiry(start, days))
    return s.learner_id
