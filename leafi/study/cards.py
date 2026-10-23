"""Card checks and stored card text (ADR-0017 §7.2): `add_cards` is the one writer of `anki_outbox` card text;
`anki.sync_outbox` sends what it stored and tags a flagged card."""

from __future__ import annotations

from leafi.core.storage import Store
from leafi.core.text import norm, words
from leafi.study import knowledge

BACK_MAX = 200


def _contains(sentence_words: list[str], key: str) -> bool:
    k = [norm(x) for x in words(key)]
    return bool(k) and any(sentence_words[i:i + len(k)] == k for i in range(len(sentence_words)))


def check(store: Store, learner_id: int, item_id: int, fields: dict[str, str], sentence: str) -> tuple[str, str]:
    """pass / flag / reject with a reason: the item occurs in the sentence; at most one item unknown to this learner
    in it (a second one flags the card); back ≤ 200 chars; no duplicate for this learner by lemma (word key)."""
    item = store.one("SELECT key FROM knowledge_items WHERE id=?", (item_id,))
    sent = [norm(x) for x in words(sentence)]
    if not _contains(sent, item["key"]):
        return "reject", "the item is not in the sentence"
    if len(fields.get("背面", "")) > BACK_MAX:
        return "reject", f"the back is over {BACK_MAX} characters"
    if store.one("SELECT o.id FROM anki_outbox o JOIN knowledge_items k ON k.id = o.knowledge_item_id WHERE "
                 "o.learner_id=? AND o.front IS NOT NULL AND lower(k.key)=lower(?) AND k.id != ?",
                 (learner_id, item["key"], item_id)):
        return "reject", "a card for this word already exists"
    others = [r["key"] for r in store.all("SELECT key FROM knowledge_items WHERE learner_id=? AND id != ? AND "
                                          "status IN ('new','learning')", (learner_id, item_id))]
    if any(_contains(sent, k) for k in others):
        return "flag", "another unknown word is in the sentence"
    return "pass", ""


def stored_text(store: Store, item_id: int) -> tuple[dict[str, str], str]:
    """The `code` content owner's card text: `knowledge.card_fields` and the latest context sentence."""
    enc = store.one("SELECT context_sentence FROM encounters WHERE knowledge_item_id=? AND context_sentence != '' "
                    "ORDER BY id DESC LIMIT 1", (item_id,))
    return knowledge.card_fields(store, item_id), enc["context_sentence"] if enc else ""
