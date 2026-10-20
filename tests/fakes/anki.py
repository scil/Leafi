"""Stateful fake AnkiConnect (v6) as an httpx transport: notes, cards, tags, reviews, lost-ack modes,
parent edits."""

from __future__ import annotations

import itertools
import json
import time

import httpx


class FakeAnki:
    def __init__(self) -> None:
        self.notes: dict[int, dict] = {}
        self.cards: dict[int, dict] = {}
        self.decks: set[str] = {"Default"}
        self.calls: list[tuple[str, dict]] = []
        self.reviews: dict[int, list[dict]] = {}
        self.down = False
        self.lose_next: set[str] = set()  # actions whose response is lost after being applied
        self._ids = itertools.count(1_700_000_000_000)

    # ---- helpers for tests
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def parent_edit(self, note_id: int, field: str, value: str) -> None:
        self.notes[note_id]["fields"][field] = value

    def add_due_card(self, front: str, back: str = "", note_id: int | None = None, interval: int = 3) -> int:
        nid = note_id or self._new_note("Leafi", "问答题", {"正面": front, "背面": back}, ["leafi"])
        cid = next(c for c, v in self.cards.items() if v["note"] == nid)
        self.cards[cid].update(due=True, interval=interval)
        return cid

    def actions(self) -> list[str]:
        return [a for a, _ in self.calls]

    # ---- protocol
    def _new_note(self, deck: str, model: str, fields: dict, tags: list[str]) -> int:
        nid = next(self._ids)
        self.notes[nid] = {"deck": deck, "model": model, "fields": dict(fields), "tags": list(tags)}
        cid = next(self._ids)
        self.cards[cid] = {"note": nid, "due": False, "interval": 0}
        return nid

    def _find_notes(self, query: str) -> list[int]:
        q = query.strip('"')
        if q.startswith("tag:"):
            tag = q[4:]
            return [n for n, v in self.notes.items() if tag in v["tags"]]
        return list(self.notes)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("anki closed", request=request)
        body = json.loads(request.content)
        action, p = body["action"], body.get("params", {})
        self.calls.append((action, p))
        result = None
        error = None
        if action == "findNotes":
            result = self._find_notes(p["query"])
        elif action == "createDeck":
            self.decks.add(p["deck"])
            result = 1
        elif action == "addNote":
            n = p["note"]
            if n["deckName"] not in self.decks:
                error = "deck was not found"
            else:
                result = self._new_note(n["deckName"], n["modelName"], n["fields"], n["tags"])
        elif action == "findCards":
            q = p["query"]
            if q.startswith("nid:"):
                nid = int(q[4:])
                result = [c for c, v in self.cards.items() if v["note"] == nid]
            elif "is:due" in q:
                result = [c for c, v in self.cards.items() if v["due"]]
            else:
                result = list(self.cards)
        elif action == "notesInfo":
            result = [{"noteId": n, "fields": {f: {"value": v, "order": i}
                                               for i, (f, v) in enumerate(self.notes[n]["fields"].items())},
                       "tags": self.notes[n]["tags"]} for n in p["notes"] if n in self.notes]
        elif action == "updateNoteFields":
            self.notes[p["note"]["id"]]["fields"].update(p["note"]["fields"])
        elif action == "cardsInfo":
            result = [{"cardId": c, "note": self.cards[c]["note"], "interval": self.cards[c]["interval"],
                       "fields": {f: {"value": v} for f, v in self.notes[self.cards[c]["note"]]["fields"].items()}}
                      for c in p["cards"] if c in self.cards]
        elif action == "answerCards":
            result = []
            for a in p["answers"]:
                c = self.cards.get(a["cardId"])
                if c is None:
                    result.append(False)
                    continue
                c["due"] = False
                self.reviews.setdefault(a["cardId"], []).append({"id": int(time.time() * 1000) + 1,
                                                                 "ease": a["ease"]})
                result.append(True)
        elif action == "getReviewsOfCards":
            result = {str(c): self.reviews.get(c, []) for c in p["cards"]}
        else:
            error = f"unsupported action {action}"
        if action in self.lose_next:
            self.lose_next.discard(action)
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(200, json={"result": result, "error": error})
