"""Knowledge items, encounters, Difficulties and the Anki card builder, each per learner (ADR-0018 §1, §7.1).

Difficulty formulas are ADR-0013 → Difficulties (the only owner); this module implements them and
recomputes inside the caller's transaction. `withdrawn` and `invalidated` miscues never contribute.
"""

from __future__ import annotations

import datetime as dt
import html
import uuid
from collections import defaultdict

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, now_iso
from leafi.core.text import norm

HALF_LIFE_DAYS = 30.0
V_CONFIRMED, V_UNSURE = 1.0, 0.3
WATCH_MIN_SESSIONS = 3
KNOWLEDGE_MIN_SESSIONS = 2


# ---------------------------------------------------------------- items and encounters


# Card fields are built from the item's encounters at push time until `add_cards` stores them (ADR-0017 §7.2, M6),
# so an outbox row's provenance is that of the explanations it will carry (plan M3 decision).
CARD_PROVENANCE = "derived_from_learner"


def upsert_item(store: Store, learner_id: int, kind: str, key: str, language: str = "en",
                sense_hint: str = "") -> int:
    """The learner's item and its first outbox `add` are created in one transaction (review 1 #16)."""
    key = key.strip()
    with store.transaction():
        row = store.one("SELECT id FROM knowledge_items WHERE learner_id=? AND kind=? AND language=? AND key=? "
                        "AND sense_hint=?", (learner_id, kind, language, key, sense_hint))
        if row:
            return row["id"]
        now = now_iso()
        item_id = learner_store.insert(store, "knowledge_items", learner_id, kind=kind, language=language, key=key,
                                       sense_hint=sense_hint, status="new", anki_item_key=str(uuid.uuid4()),
                                       created_at=now, updated_at=now)
        _queue_card(store, learner_id, item_id, "add")
    return item_id


def _queue_card(store: Store, learner_id: int, item_id: int, op: str) -> None:
    cls, sources = learner_store.prov(CARD_PROVENANCE, [learner_id])
    learner_store.insert(store, "anki_outbox", learner_id, sources=[learner_id], knowledge_item_id=item_id, op=op,
                         state="pending", updated_at=now_iso(), card_provenance_class=cls,
                         card_source_learners=sources)


def add_encounter(store: Store, item_id: int, *, session_id: int | None, trigger: str,
                  context_sentence: str = "", revision_id: int | None = None, explanation_en: str | None = None,
                  explanation_zh: str | None = None, example: str | None = None) -> int:
    """The context sentence is page text; an explanation answers the learner, so it derives from them
    (ADR-0018 §3). The owner is the item's learner."""
    learner_id = store.one("SELECT learner_id FROM knowledge_items WHERE id=?", (item_id,))["learner_id"]
    explained = any(x for x in (explanation_en, explanation_zh, example))
    ctx = learner_store.prov("page")
    exp = learner_store.prov("derived_from_learner", [learner_id]) if explained else learner_store.prov("system")
    with store.transaction():  # the encounter and the Difficulties it feeds change together (review 1 #17)
        enc = learner_store.insert(
            store, "encounters", learner_id, sources=[learner_id] if explained else (), knowledge_item_id=item_id,
            session_id=session_id, page_revision_id=revision_id, context_sentence=context_sentence,
            context_provenance_class=ctx[0], context_source_learners=ctx[1], explanation_en=explanation_en,
            explanation_zh=explanation_zh, example=example, explanation_provenance_class=exp[0],
            explanation_source_learners=exp[1], trigger=trigger, created_at=now_iso())
        store.execute("UPDATE knowledge_items SET updated_at=? WHERE id=?", (now_iso(), item_id))
        _queue_update_if_pushed(store, learner_id, item_id)
        if trigger in ("explain", "check"):
            recompute_difficulties(store, learner_id)
    return enc


def _queue_update_if_pushed(store: Store, learner_id: int, item_id: int) -> None:
    """Removed with M6's `add_cards`, the one path into Anki (ADR-0017 §7.2); kept for the v1 session."""
    pushed = store.one("SELECT id FROM anki_outbox WHERE knowledge_item_id=? AND anki_note_id IS NOT NULL "
                       "ORDER BY id DESC LIMIT 1", (item_id,))
    pending = store.one("SELECT id FROM anki_outbox WHERE knowledge_item_id=? AND state='pending'", (item_id,))
    if pushed and not pending:
        _queue_card(store, learner_id, item_id, "update")


# ---------------------------------------------------------------- Difficulties (ADR-0013)


def _days_since(iso: str, now: dt.datetime) -> float:
    t = dt.datetime.fromisoformat(iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return max(0.0, (now - t).total_seconds() / 86400.0)


def _decay(days: float) -> float:
    return 0.5 ** (days / HALF_LIFE_DAYS)


def recompute_difficulties(store: Store, learner_id: int | None, now: dt.datetime | None = None) -> None:
    """The learner's Difficulties from their own sessions; `None` recomputes every learner, one at a time (a
    correction of shared page text can invalidate anyone's miscues). Never a global DELETE (ADR-0018 §7.1)."""
    if learner_id is None:
        with store.transaction():
            for r in store.all("SELECT id FROM learners WHERE forgetting=0 ORDER BY id"):
                recompute_difficulties(store, r["id"], now)
        return
    now = now or dt.datetime.now(dt.UTC)
    with store.transaction():
        store.execute("DELETE FROM difficulties WHERE learner_id=?", (learner_id,))
        # words: per (miscue_key, session) the best evidence
        per: dict[str, dict[int, tuple[float, str]]] = defaultdict(dict)
        for r in store.all(
            "SELECT m.expected, m.status, s.id AS sid, s.started_at FROM miscues m "
            "JOIN page_reads pr ON pr.id = m.page_read_id JOIN reading_sessions s ON s.id = pr.session_id "
            "WHERE m.status IN ('confirmed','unsure') AND s.learner_id=?", (learner_id,)):
            key = norm(r["expected"])
            v = V_CONFIRMED if r["status"] == "confirmed" else V_UNSURE
            prev = per[key].get(r["sid"])
            if prev is None or v > prev[0]:
                per[key][r["sid"]] = (v, r["started_at"])
        for key, sessions in per.items():
            confirmed = [s for s, (v, _) in sessions.items() if v == V_CONFIRMED]
            if confirmed:
                kind = "confirmed"
            elif len(sessions) >= WATCH_MIN_SESSIONS:
                kind = "watch"
            else:
                continue
            weight = sum(v * _decay(_days_since(t, now)) for v, t in sessions.values())
            learner_store.insert(store, "difficulties", learner_id, miscue_key=key,
                                 sessions_seen=dumps(sorted(sessions)), weight=weight, kind=kind,
                                 updated_at=now_iso())
        # knowledge items: sessions with an explain or check(incorrect) encounter
        items: dict[int, dict[int, str]] = defaultdict(dict)
        for r in store.all(
            "SELECT e.knowledge_item_id AS kid, s.id AS sid, s.started_at FROM encounters e "
            "JOIN reading_sessions s ON s.id = e.session_id WHERE e.trigger IN ('explain','check') "
            "AND e.learner_id=?", (learner_id,)):
            items[r["kid"]][r["sid"]] = r["started_at"]
        for kid, sessions in items.items():
            if len(sessions) < KNOWLEDGE_MIN_SESSIONS:
                continue
            weight = sum(_decay(_days_since(t, now)) for t in sessions.values())
            learner_store.insert(store, "difficulties", learner_id, knowledge_item_id=kid,
                                 sessions_seen=dumps(sorted(sessions)), weight=weight, kind="knowledge",
                                 updated_at=now_iso())


def word_weights(store: Store, learner_id: int) -> dict[str, float]:
    return {r["miscue_key"]: r["weight"] for r in
            store.all("SELECT miscue_key, weight FROM difficulties WHERE miscue_key IS NOT NULL AND learner_id=?",
                      (learner_id,))}


def practice_order(store: Store, learner_id: int, candidates: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Order (token_index, expected) by the learner's Difficulty weight (high first), then position."""
    w = word_weights(store, learner_id)
    return sorted(candidates, key=lambda c: (-w.get(norm(c[1]), 0.0), c[0]))


# ---------------------------------------------------------------- Anki card builder


def card_fields(store: Store, item_id: int) -> dict[str, str]:
    """Bilingual English-first card (anki-cards skill layout): short front, explanation + example back."""
    item = store.one("SELECT * FROM knowledge_items WHERE id=?", (item_id,))
    enc = store.one("SELECT * FROM encounters WHERE knowledge_item_id=? ORDER BY "
                    "(explanation_en IS NULL), id DESC LIMIT 1", (item_id,))
    front = html.escape(item["key"])
    back_parts: list[str] = []
    if enc is not None:
        if enc["explanation_en"]:
            back_parts.append(html.escape(enc["explanation_en"]))
        if enc["explanation_zh"]:
            back_parts.append(html.escape(enc["explanation_zh"]))
        if enc["example"]:
            back_parts.append("<i>" + html.escape(enc["example"]) + "</i>")
        elif enc["context_sentence"]:
            back_parts.append("<i>" + html.escape(enc["context_sentence"]) + "</i>")
    return {"正面": front, "背面": "<br>".join(back_parts) or front}
