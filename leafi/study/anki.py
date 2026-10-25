"""Anki synchronisation (ADR-0004 as amended): AnkiConnect client, the local outbox, review answers.

- The link is `knowledge_items.anki_item_key` + note tag `leafi-id::<key>`; Anki ids live in the outbox.
- Before any `addNote`, `findNotes "tag:leafi-id::<key>"` dedupes a lost acknowledgement.
- Parent edits win: a field is updated only when its remote value still hashes to the last acked value.
- Review answers go pending → sent (immediately before `answerCards`) → acked; a `sent` answer is never
  replayed; `reconcile()` marks it acked when Anki shows a review after `sent_at`.
AnkiConnect is on loopback (127.0.0.1:8765); Anki closed → everything stays pending.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.study import knowledge
from leafi.study.books import slug

log = logging.getLogger("leafi.anki")
# ADR-0018 §2 (owner decision 2026-10-22): shown by `leafi setup`, `leafi doctor` and the settings page (ANKI_URL)
NOTICE = ("Anki can sync your cards to AnkiWeb. Card text can include what Leafi learned from your child's answers. "
          "Check your Anki sync setting.")
MAX_ATTEMPTS = 5
EASES = (1, 2, 3, 4)  # again, hard, good, easy (ADR-0017 §3.1)


def _overlaps(a: str, b: str) -> bool:
    """Anki's `deck:` search includes subdecks, so two learners' decks may be neither equal nor nested."""
    a, b = a.casefold(), b.casefold()
    return a == b or a.startswith(b + "::") or b.startswith(a + "::")


def deck_for(store: Store, learner_id: int, base: str = "Leafi") -> str:
    """Each learner's own deck (ADR-0018 §1), stored in the learner's `anki.deck` setting the first time it is
    needed and never recomputed, so a rename or a namesake never moves or shares cards (codex M3 #1). Migration 5
    gives the first learner the household's existing deck; later learners get a top-level `<base> <name> #<id>`,
    unique by id and never a subdeck of another learner's."""
    with store.transaction():
        row = learner_store.get(store, learner_id)
        if row is None:
            raise LookupError(f"learner {learner_id}")
        settings = loads(row["settings"], {})
        if settings.get("anki.deck"):
            return settings["anki.deck"]
        taken = [loads(r["settings"], {}).get("anki.deck") for r in
                 store.all("SELECT settings FROM learners WHERE id<>?", (learner_id,))]
        deck = f"{base} {row['display_name']} #{learner_id}"
        if any(t and _overlaps(deck, t) for t in taken):
            raise AnkiError(f"deck {deck!r} would overlap another learner's deck; set anki.deck by hand")
        settings["anki.deck"] = deck
        store.execute("UPDATE learners SET settings=?, settings_version=settings_version+1 WHERE id=?",
                      (dumps(settings), learner_id))
    return deck


class AnkiUnavailable(RuntimeError):
    """Transport failure: the request may or may not have reached Anki."""


class AnkiError(RuntimeError):
    """AnkiConnect answered with an error."""


class AnkiClient:
    def __init__(self, url: str = "http://127.0.0.1:8765", *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 10.0) -> None:
        self.url = url
        self._transport = transport
        self.timeout = timeout

    async def invoke(self, action: str, **params: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as c:
                r = await c.post(self.url, json={"action": action, "version": 6, "params": params})
                r.raise_for_status()
                body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise AnkiUnavailable(f"{action}: {type(e).__name__}") from e
        if body.get("error"):
            raise AnkiError(f"{action}: {body['error']}")
        return body.get("result")

    async def find_notes(self, query: str) -> list[int]:
        return list(await self.invoke("findNotes", query=query) or [])

    async def find_cards(self, query: str) -> list[int]:
        return list(await self.invoke("findCards", query=query) or [])

    async def notes_info(self, notes: list[int]) -> list[dict]:
        return list(await self.invoke("notesInfo", notes=notes) or [])

    async def cards_info(self, cards: list[int]) -> list[dict]:
        return list(await self.invoke("cardsInfo", cards=cards) or [])


def field_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass
class SyncReport:
    acked: int = 0
    deduped: int = 0
    pending: int = 0
    failed: int = 0
    conflicts: list[str] = field(default_factory=list)


def _item_tags(store: Store, item_id: int, key: str) -> list[str]:
    tags = ["leafi", f"leafi-id::{key}"]
    r = store.one("SELECT b.title FROM encounters e JOIN reading_sessions s ON s.id = e.session_id "
                  "JOIN books b ON b.id = s.book_id WHERE e.knowledge_item_id=? ORDER BY e.id DESC LIMIT 1",
                  (item_id,))
    if r:
        tags.append(f"leafi::{slug(r['title'])}")
    return tags


def _forgotten_while_sent(store: Store, learner_id: int, note_id: int) -> None:
    """`forget` deleted the outbox row while `addNote` was awaited (ADR-0021 E9, Y4): list the note for the
    household to remove while the learner row still exists, else only log it."""
    from leafi.study import records

    log.warning("anki note %s was added for learner #%s while that learner was being forgotten", note_id, learner_id)
    with store.transaction():
        if learner_store.get(store, learner_id) is not None:
            records._remember_notes(store, learner_id, [note_id])


async def sync_outbox(store: Store, client: AnkiClient, deck: str = "Leafi", model: str = "问答题", *,
                      tz: str = "", known_days: float = 21) -> SyncReport:
    """Every learner's pending cards, each into that learner's deck (`deck` is the base name, `deck_for`). A learner
    being forgotten is skipped (ADR-0021 E9, X4): their rows are not read, and the claim to `'sent'` checks the
    owner in its own statement. Each acknowledged card gets a `card_ack` (M7 design D17) after the outbox row's
    acknowledgement, so a refusal never loses `anki_note_id`."""
    rep = SyncReport()
    rows = store.all("SELECT o.*, k.anki_item_key FROM anki_outbox o JOIN knowledge_items k ON "
                     "k.id = o.knowledge_item_id JOIN learners l ON l.id = o.learner_id "
                     "WHERE o.state IN ('pending','sent') AND l.forgetting = 0 ORDER BY o.id")
    decks_ready: set[str] = set()
    for row in rows:
        oid, item_id, key = row["id"], row["knowledge_item_id"], row["anki_item_key"]
        learner_deck = deck_for(store, row["learner_id"], deck)
        stored = row["front"] is not None  # written by `add_cards` (ADR-0017 §7.2): push sends what was stored
        fields = {"正面": row["front"], "背面": row["back"] or ""} if stored else knowledge.card_fields(store, item_id)
        tags = _item_tags(store, item_id, key)
        if stored:
            from leafi.study import cards

            if cards.check(store, row["learner_id"], item_id, fields, row["sentence"] or "")[0] == "flag":
                tags.append("leafi-check")  # a flagged card goes with a tag the learner sees (§7.2)
        claimed = store.execute(
            "UPDATE anki_outbox SET state='sent', attempts=attempts+1, updated_at=?, "
            "attempted_fields=COALESCE(attempted_fields, ?) WHERE id=? AND EXISTS(SELECT 1 FROM learners l "
            "WHERE l.id = anki_outbox.learner_id AND l.forgetting = 0)",
            (now_iso(), dumps({f: field_hash(v) for f, v in fields.items()}) if row["op"] == "add" else None,
             oid)).rowcount
        if not claimed:  # marked for forgetting since the query: not pushed
            continue
        try:
            if row["op"] == "add":
                note_id = None
                found = await client.find_notes(f'"tag:leafi-id::{key}"')
                if found:
                    # A lost acknowledgement: Leafi owns only what it attempted; a remote value that differs is
                    # the parent's and must stay theirs (parent edits win).
                    note_id = found[0]
                    attempted = store.one("SELECT attempted_fields FROM anki_outbox WHERE id=?", (oid,))
                    acked = loads(attempted["attempted_fields"], {}) if attempted else {}
                    rep.deduped += 1
                else:
                    if learner_deck not in decks_ready:
                        await client.invoke("createDeck", deck=learner_deck)
                        decks_ready.add(learner_deck)
                    note_id = await client.invoke("addNote", note={
                        "deckName": learner_deck, "modelName": model, "fields": fields,
                        "tags": tags, "options": {"allowDuplicate": False}})
                    acked = {f: field_hash(v) for f, v in fields.items()}
                cards = await client.find_cards(f"nid:{note_id}")
                acked_rows = store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=?, card_ids=?, "
                                           "last_acked_fields=?, last_error=NULL, updated_at=? WHERE id=?",
                                           (note_id, dumps(cards), dumps(acked), now_iso(), oid)).rowcount
                if not acked_rows:
                    _forgotten_while_sent(store, row["learner_id"], note_id)
                    continue
                rep.acked += 1
                _ack_cards(store, row["learner_id"], item_id, [int(c) for c in cards], tz=tz, known_days=known_days)
            else:
                prev = store.one("SELECT anki_note_id, card_ids, last_acked_fields FROM anki_outbox WHERE "
                                 "knowledge_item_id=? AND state='acked' AND anki_note_id IS NOT NULL "
                                 "ORDER BY id DESC LIMIT 1", (item_id,))
                if prev is None:
                    raise AnkiError("update before any acknowledged add")
                note_id = prev["anki_note_id"]
                last = loads(prev["last_acked_fields"], {})
                info = (await client.notes_info([note_id]))[0]
                remote = {f: v["value"] for f, v in info["fields"].items()}
                update: dict[str, str] = {}
                acked = dict(last)
                for f, value in fields.items():
                    if f in remote and field_hash(remote[f]) != last.get(f):
                        rep.conflicts.append(f"note {note_id} field {f}: parent edit kept")
                        continue
                    if remote.get(f) != value:
                        update[f] = value
                    acked[f] = field_hash(value)
                if update:
                    await client.invoke("updateNoteFields", note={"id": note_id, "fields": update})
                err = "; ".join(rep.conflicts) or None
                store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=?, card_ids=?, "
                              "last_acked_fields=?, last_error=?, updated_at=? WHERE id=?",
                              (note_id, prev["card_ids"], dumps(acked), err, now_iso(), oid))
                rep.acked += 1
                _ack_cards(store, row["learner_id"], item_id, [int(c) for c in loads(prev["card_ids"], [])], tz=tz,
                           known_days=known_days)
        except AnkiUnavailable as e:
            store.execute("UPDATE anki_outbox SET state='pending', last_error=?, updated_at=? WHERE id=?",
                          (str(e), now_iso(), oid))
            rep.pending += 1
            log.info("anki unavailable; outbox kept pending")
            break
        except AnkiError as e:
            attempts = store.one("SELECT attempts FROM anki_outbox WHERE id=?", (oid,))["attempts"]
            state = "failed" if attempts >= MAX_ATTEMPTS else "pending"
            store.execute("UPDATE anki_outbox SET state=?, last_error=?, updated_at=? WHERE id=?",
                          (state, str(e), now_iso(), oid))
            rep.failed += state == "failed"
            rep.pending += state == "pending"
    return rep


# ---------------------------------------------------------------- review


@dataclass(frozen=True)
class DueCard:
    card_id: int
    knowledge_item_id: int | None
    front: str
    interval: int


async def due_cards(store: Store, client: AnkiClient, learner_id: int, deck: str = "Leafi",
                    limit: int = 5) -> list[DueCard]:
    """Due cards of the learner's own deck; a note maps to an item only when the item is this learner's."""
    own = deck_for(store, learner_id, deck)
    ids = (await client.find_cards(f'"deck:{own}" -"deck:{own}::*" is:due'))[:limit]  # a subdeck is not this learner's
    if not ids:
        return []
    out = []
    for c in await client.cards_info(ids):
        if not c or not c.get("cardId"):  # AnkiConnect's empty entry for a card deleted since `findCards`
            continue
        r = store.one("SELECT knowledge_item_id FROM anki_outbox WHERE anki_note_id=? AND learner_id=? "
                      "ORDER BY id DESC LIMIT 1", (c.get("note"), learner_id))
        front = (c.get("fields", {}).get("正面", {}) or {}).get("value", "") or c.get("question", "")
        out.append(DueCard(c["cardId"], r["knowledge_item_id"] if r else None, front, int(c.get("interval", 0))))
    return out


async def answer(store: Store, client: AnkiClient, learner_id: int, card: DueCard, ease: int,
                 known_days: float = 21, *, tz: str = "", activity_id: int | None = None) -> str:
    """Write pending, set sent immediately before `answerCards`, acked on response. Never replayed. An
    acknowledged answer records the card's new state (`card_state`, M7 design D17) and re-folds its item."""
    if ease not in EASES:
        raise ValueError(f"ease {ease}: 1 again, 2 hard, 3 good, 4 easy")
    rid = learner_store.insert(store, "review_answers", learner_id, knowledge_item_id=card.knowledge_item_id,
                               card_id=card.card_id, ease=ease, state="pending", created_at=now_iso())
    sent_at = now_iso()
    store.execute("UPDATE review_answers SET state='sent', sent_at=? WHERE id=?", (sent_at, rid))
    try:
        result = await client.invoke("answerCards", answers=[{"cardId": card.card_id, "ease": ease}])
    except AnkiUnavailable:
        log.warning("answerCards response lost; answer %d stays sent (never replayed)", rid)
        return "sent"
    except AnkiError:
        store.execute("UPDATE review_answers SET state='failed' WHERE id=?", (rid,))
        return "failed"
    if result and result[0]:
        store.execute("UPDATE review_answers SET state='acked', acked_at=? WHERE id=?", (now_iso(), rid))
        await _record_state(store, client, learner_id, card.knowledge_item_id, card.card_id, sent_at, None,
                            tz=tz, known_days=known_days, activity_id=activity_id)
        return "acked"
    store.execute("UPDATE review_answers SET state='failed' WHERE id=?", (rid,))
    return "failed"


def _review_after(reviews, card_id: int, sent_at: str) -> dict | None:
    """The latest revlog entry of `card_id` at or after `sent_at` (revlog ids are epoch milliseconds)."""
    sent_ms = dt.datetime.fromisoformat(sent_at).timestamp() * 1000
    entries = (reviews or {}).get(str(card_id)) or (reviews or {}).get(card_id) or []
    after = [e for e in entries if e.get("id", 0) >= sent_ms]
    return max(after, key=lambda e: e.get("id", 0)) if after else None


async def _record_state(store: Store, client: AnkiClient, learner_id: int, item_id: int | None, card_id: int,
                        sent_at: str, reviews, *, tz: str, known_days: float, activity_id: int | None) -> None:
    """A `card_state` from the review after `sent_at` (interval, type) and `cardsInfo` (lapses); session NULL, since
    it describes the card, not the session. Anki unreachable: nothing, `observe_cards` catches up."""
    if item_id is None:
        return
    from leafi.study import item_status

    try:
        if reviews is None:
            reviews = await client.invoke("getReviewsOfCards", cards=[card_id])
        info = await client.cards_info([card_id])
    except (AnkiUnavailable, AnkiError):
        return
    entry = _review_after(reviews, card_id, sent_at)
    card = info[0] if info else {}
    if entry is None or not card.get("cardId"):
        return
    try:
        item_status.record(store, learner_id, item_id, "card_state", "anki", tz=tz, known_days=known_days,
                           activity_id=activity_id, card_id=card_id, ivl=item_status.ivl_days(entry.get("ivl", 0)),
                           lapses=int(card.get("lapses", 0)), revlog_id=entry.get("id"), revlog_type=entry.get("type"))
    except learner_store.LearnerUnavailable:
        log.info("card state of a learner being forgotten not recorded")


async def reconcile(store: Store, client: AnkiClient, known_days: float = 21, *, tz: str = "") -> list[int]:
    """`sent` answers of learners not being forgotten: acked when Anki has a review after `sent_at`, recording the
    card's state as a normal acknowledgement does (once: only `sent` rows are looked at); the rest are returned."""
    unknown = []
    for r in store.all("SELECT a.* FROM review_answers a JOIN learners l ON l.id = a.learner_id "
                       "WHERE a.state='sent' AND l.forgetting = 0"):
        try:
            reviews = await client.invoke("getReviewsOfCards", cards=[r["card_id"]])
        except (AnkiUnavailable, AnkiError):
            unknown.append(r["id"])
            continue
        if _review_after(reviews, r["card_id"], r["sent_at"]) is None:
            unknown.append(r["id"])
            continue
        store.execute("UPDATE review_answers SET state='acked', acked_at=? WHERE id=?", (now_iso(), r["id"]))
        await _record_state(store, client, r["learner_id"], r["knowledge_item_id"], r["card_id"], r["sent_at"],
                            reviews, tz=tz, known_days=known_days, activity_id=None)
    return unknown


def _ack_cards(store: Store, learner_id: int, item_id: int, card_ids: list[int], *, tz: str,
               known_days: float) -> None:
    """A `card_ack` per card id with no live membership (no event, or its latest is `card_gone`), written after the
    outbox acknowledgement and never inside it (round 10 #3); a learner being forgotten: logged, not written."""
    from leafi.study import item_status

    latest = item_status.latest_card_events(store, learner_id)
    for cid in card_ids:
        ev = latest.get(cid)
        if ev is not None and ev["event"] != "card_gone":
            continue
        try:
            item_status.record(store, learner_id, item_id, "card_ack", "anki", tz=tz, known_days=known_days,
                               card_id=cid)
        except learner_store.LearnerUnavailable:
            log.info("card acknowledgement of a learner being forgotten not recorded")
            return


async def observe_cards(store: Store, client: AnkiClient, learner_id: int, *, tz: str = "",
                        known_days: float = 21) -> int:
    """Once per session, when Anki is reachable (D17): `cardsInfo` over every card of the learner's acknowledged
    outbox rows, writing a `card_state` when the interval or lapses changed (or a gone card came back) and a
    `card_gone` when Anki answers without the card. Anki errors propagate untouched; nothing is written then."""
    from leafi.study import item_status

    if store.one("SELECT 1 FROM learners WHERE id=? AND forgetting = 0", (learner_id,)) is None:
        return 0
    tracked: dict[int, int] = {}
    for r in store.all("SELECT knowledge_item_id, card_ids FROM anki_outbox WHERE learner_id=? AND state='acked' "
                       "ORDER BY id", (learner_id,)):
        for cid in loads(r["card_ids"], []):
            tracked[int(cid)] = r["knowledge_item_id"]
    if not tracked:
        return 0
    ids = sorted(tracked)
    found: dict[int, dict] = {}
    for i in range(0, len(ids), 100):
        for c in await client.cards_info(ids[i:i + 100]):
            if c and c.get("cardId"):
                found[int(c["cardId"])] = c
    latest = item_status.latest_card_events(store, learner_id)
    states = item_status.latest_card_states(store, learner_id)
    written = 0
    for cid in ids:
        ev, c = latest.get(cid), found.get(cid)
        try:
            if c is None:
                if ev is not None and ev["event"] != "card_gone":
                    item_status.record(store, learner_id, tracked[cid], "card_gone", "anki", tz=tz,
                                       known_days=known_days, card_id=cid)
                    written += 1
                continue
            ivl, lapses = item_status.ivl_days(c.get("interval", 0)), int(c.get("lapses", 0))
            st = states.get(cid)
            if (ev is None or ev["event"] == "card_gone" or st is None or st["ivl_days"] != ivl
                    or st["lapses"] != lapses):
                item_status.record(store, learner_id, tracked[cid], "card_state", "anki", tz=tz,
                                   known_days=known_days, card_id=cid, ivl=ivl, lapses=lapses)
                written += 1
        except learner_store.LearnerUnavailable:
            log.info("card states of a learner being forgotten not recorded")
            return written
    return written
