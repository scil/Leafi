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


async def sync_outbox(store: Store, client: AnkiClient, deck: str = "Leafi", model: str = "问答题") -> SyncReport:
    """Every learner's pending cards, each into that learner's deck (`deck` is the base name, `deck_for`)."""
    rep = SyncReport()
    rows = store.all("SELECT o.*, k.anki_item_key FROM anki_outbox o JOIN knowledge_items k ON "
                     "k.id = o.knowledge_item_id WHERE o.state IN ('pending','sent') ORDER BY o.id")
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
        store.execute("UPDATE anki_outbox SET state='sent', attempts=attempts+1, updated_at=?, "
                      "attempted_fields=COALESCE(attempted_fields, ?) WHERE id=?",
                      (now_iso(), dumps({f: field_hash(v) for f, v in fields.items()}) if row["op"] == "add" else None,
                       oid))
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
                store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=?, card_ids=?, "
                              "last_acked_fields=?, last_error=NULL, updated_at=? WHERE id=?",
                              (note_id, dumps(cards), dumps(acked), now_iso(), oid))
                rep.acked += 1
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
        r = store.one("SELECT knowledge_item_id FROM anki_outbox WHERE anki_note_id=? AND learner_id=? "
                      "ORDER BY id DESC LIMIT 1", (c.get("note"), learner_id))
        front = (c.get("fields", {}).get("正面", {}) or {}).get("value", "") or c.get("question", "")
        out.append(DueCard(c["cardId"], r["knowledge_item_id"] if r else None, front, int(c.get("interval", 0))))
    return out


async def answer(store: Store, client: AnkiClient, learner_id: int, card: DueCard, ease: int,
                 known_days: int = 21) -> str:
    """Write pending, set sent immediately before `answerCards`, acked on response. Never replayed."""
    if ease not in EASES:
        raise ValueError(f"ease {ease}: 1 again, 2 hard, 3 good, 4 easy")
    rid = learner_store.insert(store, "review_answers", learner_id, knowledge_item_id=card.knowledge_item_id,
                               card_id=card.card_id, ease=ease, state="pending", created_at=now_iso())
    store.execute("UPDATE review_answers SET state='sent', sent_at=? WHERE id=?", (now_iso(), rid))
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
        _update_status(store, card, ease, known_days)
        return "acked"
    store.execute("UPDATE review_answers SET state='failed' WHERE id=?", (rid,))
    return "failed"


def _update_status(store: Store, card: DueCard, ease: int, known_days: int) -> None:
    if card.knowledge_item_id is None:
        return
    cur = store.one("SELECT status FROM knowledge_items WHERE id=?", (card.knowledge_item_id,))["status"]
    passed = ease >= 3  # hard (2) is remembered with effort: it neither promotes nor lapses an item
    new = cur
    if cur == "new":
        new = "learning"
    elif cur == "learning" and passed and card.interval >= known_days:
        new = "known"
    elif cur == "known" and ease == 1:
        new = "lapsed"
    elif cur == "lapsed" and passed:
        new = "learning"
    if new != cur:
        store.execute("UPDATE knowledge_items SET status=?, updated_at=? WHERE id=?",
                      (new, now_iso(), card.knowledge_item_id))


async def reconcile(store: Store, client: AnkiClient, known_days: int = 21) -> list[int]:
    """`sent` answers: acked when Anki has a review after `sent_at`, applying the same knowledge-status
    transition as a normal acknowledgement (once: only `sent` rows are looked at); the rest are returned."""
    unknown = []
    for r in store.all("SELECT * FROM review_answers WHERE state='sent'"):
        try:
            reviews = await client.invoke("getReviewsOfCards", cards=[r["card_id"]])
        except (AnkiUnavailable, AnkiError):
            unknown.append(r["id"])
            continue
        sent_ms = dt.datetime.fromisoformat(r["sent_at"]).timestamp() * 1000
        entries = (reviews or {}).get(str(r["card_id"])) or (reviews or {}).get(r["card_id"]) or []
        if any(e.get("id", 0) >= sent_ms for e in entries):
            interval = 0
            try:
                info = await client.cards_info([r["card_id"]])
                interval = int(info[0].get("interval", 0)) if info else 0
            except (AnkiUnavailable, AnkiError):
                pass
            with store.transaction():
                store.execute("UPDATE review_answers SET state='acked', acked_at=? WHERE id=?", (now_iso(), r["id"]))
                _update_status(store, DueCard(r["card_id"], r["knowledge_item_id"], "", interval), r["ease"],
                               known_days)
        else:
            unknown.append(r["id"])
    return unknown
