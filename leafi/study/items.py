"""What is new for a learner, and in what order (ADR-0017 §6.2; M7 design D17's ranking, owner decisions O5, O6).

Known = this learner's items in `known` or `ignored`, or a function word; `new`, `learning` and `lapsed` count as
unknown (O6, as the card checks do). New-item candidates are the unknown content words of the open cycle's read
sentences that have no item yet or an item in `new`, ranked: sentences with exactly one unknown word first
(AnkiMorphs' i+1), then the CYP-LEX level band (O5: YLE waits for its parser), then the order read. CYP-LEX's
frequencies are not kept in `cyplex.txt`, so frequency is not a key yet (plan Decision log 2026-10-24).
"""

from __future__ import annotations

from leafi.core.storage import Store
from leafi.core.text import norm, words
from leafi.core.wordinfo import WordInfo
from leafi.study import knowledge
from leafi.study.function_words import FUNCTION_WORDS

UNKNOWN = ("new", "learning", "lapsed")
KNOWN = ("known", "ignored")


def statuses(store: Store, learner_id: int) -> dict[str, str]:
    """The learner's word items: normed key → status."""
    return {norm(r["key"]): r["status"] for r in store.all(
        "SELECT key, status FROM knowledge_items WHERE learner_id=? AND kind='word'", (learner_id,))}


def is_known(word: str, known: dict[str, str], info: WordInfo) -> bool:
    w = norm(word)
    return w in FUNCTION_WORDS or any(known.get(x) in KNOWN for x in {w} | set(info.lemmas(w)))


def band(word: str, info: WordInfo) -> int:
    """0 for a word of the children's-book lists (CYP-LEX, ages 7–12), 1 otherwise; 0 when the backend has no
    lists, so the band then orders nothing."""
    f = getattr(info, "band", None)
    return f(word) if f is not None else 0


def new_candidates(store: Store, learner_id: int, sentences: list[str], info: WordInfo, limit: int) -> list[int]:
    """Up to `limit` item ids, best first; an item row is created (status `new`) only for the words chosen."""
    if limit <= 0:
        return []
    known = statuses(store, learner_id)
    ranked: dict[str, tuple] = {}
    for si, text in enumerate(sentences):
        ws = [n for n in (norm(x) for x in words(text)) if n]
        info.prepare(ws)
        content = [x for x in ws if x not in FUNCTION_WORDS and not x.isdigit() and info.is_word(x)]
        unknown = list(dict.fromkeys(x for x in content if not is_known(x, known, info)))
        for wi, x in enumerate(unknown):
            if known.get(x, "new") != "new":
                continue  # learning or lapsed: recalled, not taught again
            key = (len(unknown) != 1, band(x, info), si, wi)
            if x not in ranked or key < ranked[x]:
                ranked[x] = key
    chosen = sorted(ranked, key=ranked.__getitem__)[:limit]
    return [knowledge.upsert_item(store, learner_id, "word", x) for x in chosen]
