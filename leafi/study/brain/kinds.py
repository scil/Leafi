"""The `generate` kinds construction can call (ADR-0017 §3.1; M7 design D15): what each request carries and how
its reply is bound before an activity may use it.

What a request carries (D3, D15; owner decision 2026-10-24): first the session's cached learner context
(`generate.learner_context`: Difficulties, this cycle's errors expected and heard, filtered per leaf by D3), then
the kind's own leaves — the cited sentences of this learner's page reads with rendered ids, and the item keys, which
come from the page. Stored explanations are not sent.

References are bound, not just existing (D15): an id is valid only when this request rendered it, for this learner,
and a sentence only when its page read is at its page's current revision; duplicates are dropped. An item cited by
a quiz question must have its key in that question's text, answers or cited sentences.

Quiz answerability (D15): per question, cited evidence; a CROWD type; for `completion`, `recall` and `wh-` a
non-empty list of keyword sets, each with a content word, and **every** set supported by the cited sentences (a
question with any unsupported set is dropped); for `open-ended` and `distancing` no answers. A quiz with no question
left is rejected. This checks support, not meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

from leafi.core.ports import Leaf, Section
from leafi.core.storage import loads
from leafi.core.text import norm, words
from leafi.study import pages, phrases
from leafi.study.alignment import ReadingState
from leafi.study.brain import prompts, schemas
from leafi.study.brain.generate import GENERATORS, Generator
from leafi.study.function_words import FUNCTION_WORDS
from leafi.study.harness.state import Rejected

KEYWORD_TYPES = ("completion", "recall", "wh-")
OPEN_TYPES = ("open-ended", "distancing")


@dataclass(frozen=True)
class Sentence:
    rid: str          # s<page_read_id>.<sentence_index>
    read_id: int
    sid: int
    text: str


def _reads(s, where: str, args: tuple):
    """This learner's page reads matching `where`, each with its state over the current revision (D15)."""
    from leafi.study import coach

    out = []
    for r in s.store.all(
            "SELECT pr.id, pr.page_id, pr.page_revision_id, pr.reading_state FROM page_reads pr "
            "JOIN reading_sessions rs ON rs.id = pr.session_id WHERE rs.learner_id=? AND pr.reading_state IS NOT NULL "
            f"AND {where} ORDER BY pr.id", (s.learner_id, *args)):
        rev = pages.current_revision(s.store, r["page_id"])
        if rev is None or rev.id != r["page_revision_id"]:
            continue  # a correction since: its sentence ids no longer name this text
        st = ReadingState.from_json(rev.text, loads(r["reading_state"], {}))
        out.append((r["id"], st, lambda sid, st=st, text=rev.text: coach.sentence_text(text, st, sid)))
    return out


def cycle_sentences(s) -> list[Sentence]:
    """The sentences read in the open cycle (the quiz's facts, §3.1)."""
    if s.cycle_id is None:
        return []
    return [Sentence(f"s{rid}.{sid}", rid, sid, text(sid))
            for rid, st, text in _reads(s, "pr.cycle_id=?", (s.cycle_id,)) for sid in sorted(st.completed)]


def current_sentences(s, rng) -> list[Sentence]:
    """The unread sentences of the session's latest page read in `rng` (what `read_aloud` on `current` reads)."""
    reads = _reads(s, "pr.session_id=?", (s.session_id,))
    if not reads:
        return []
    rid, st, text = reads[-1]
    start = st.tokens[st.ccur].sentence_id if st.ccur < st.n else None
    sids = [i for i in st.sentence_ids() if start is not None and i >= start
            and (not isinstance(rng, dict) or rng["from"] <= i <= rng["to"])]
    return [Sentence(f"s{rid}.{sid}", rid, sid, text(sid)) for sid in sids]


def _section(name: str, leaves: list[Leaf]) -> Section:
    return Section(name, tuple(leaves))


def _bind(rendered: dict, refs: list[str]) -> list:
    out = []
    for r in refs:
        hit = rendered.get(r)
        if hit is not None and hit not in out:
            out.append(hit)
    return out


def _norms(text: str) -> list[str]:
    return [n for n in (norm(w) for w in words(text)) if n]


# ---------------------------------------------------------------- quiz


def _items_on(s, sentences: list[Sentence]) -> list[tuple[int, str]]:
    """This learner's items whose key occurs in the sentences (rendered so a question may cite them)."""
    present = " " + " ".join(" ".join(_norms(x.text)) for x in sentences) + " "
    rows = s.store.all("SELECT id, key FROM knowledge_items WHERE learner_id=? AND status != 'ignored' ORDER BY id",
                       (s.learner_id,))
    return [(r["id"], r["key"]) for r in rows if _norms(r["key"]) and f" {' '.join(_norms(r['key']))} " in present]


def _quiz_facts(s, sel):
    sentences = cycle_sentences(s)
    wanted = set(sel.get("evidence_sentence_ids") or ())
    if wanted:
        sentences = [x for x in sentences if x.rid in wanted] or sentences
    return sentences, _items_on(s, sentences)


def quiz_sections(s, sel) -> tuple[Section, ...] | Rejected:
    sentences, items = _quiz_facts(s, sel)
    if not sentences:
        return Rejected("no read sentences")
    n = s.ledger.cycle_quiz_left(s.cycle_id)
    return (_section("page", [Leaf(f"{x.rid}: {x.text}", book=True) for x in sentences]),
            _section("cycle", [Leaf(f"i{i} '{k}'", book=True) for i, k in items]),
            _section("limits", [Leaf(f"at most {n} questions")]))


def _supported(keywords: list[str], evidence_words: set[str]) -> bool:
    ws = [w for k in keywords for w in _norms(k)]
    return bool(ws) and any(w not in FUNCTION_WORDS for w in ws) and all(w in evidence_words for w in ws)


def quiz_check(s, sel, value: schemas.QuizContent) -> dict | Rejected:
    sentences, items = _quiz_facts(s, sel)
    by_rid = {x.rid: x for x in sentences}
    keys = {f"i{i}": (i, k) for i, k in items}
    out = []
    for q in value.questions:
        cited = _bind(by_rid, q.evidence)
        if not cited or not phrases.safe(q.text):  # a line shown to the child passes the deny-list
            continue
        evidence_words = {w for x in cited for w in _norms(x.text)}
        if q.type in KEYWORD_TYPES:
            if not q.answers or not all(_supported(ks, evidence_words) for ks in q.answers):
                continue  # any unsupported set drops the question
        elif q.answers:
            continue  # open-ended and distancing carry no answers
        said = {w for w in _norms(q.text)} | {w for ks in q.answers for k in ks for w in _norms(k)} | evidence_words
        cited_items = [i for i, k in _bind(keys, q.item_ids) if set(_norms(k)) <= said]
        out.append({"text": q.text, "type": q.type, "answers": [list(ks) for ks in q.answers],
                    "item_ids": cited_items, "evidence": [x.text for x in cited]})
    out = out[: s.ledger.cycle_quiz_left(s.cycle_id)]
    return {"questions": out} if out else Rejected("no answerable question")


# ---------------------------------------------------------------- read_aloud


def read_aloud_sections(s, sel) -> tuple[Section, ...] | Rejected:
    if sel.get("page") != "current":
        return Rejected("its text is not known until the page is open")
    sentences = current_sentences(s, sel.get("range", "rest"))
    if not sentences:
        return Rejected("nothing left to read on this page")
    return (_section("page", [Leaf(f"{x.rid}: {x.text}", book=True) for x in sentences]),)


def read_aloud_check(s, sel, value: schemas.ReadAloudContent) -> dict | Rejected:
    by_rid = {x.rid: x for x in current_sentences(s, sel.get("range", "rest"))}
    return {"translate": value.translate.strip(), "hard_sentence_ids": [x.sid for x in _bind(
        by_rid, value.hard_sentence_ids)][:3]}


# ---------------------------------------------------------------- add_cards


def _contexts(s, item_ids: list[int]) -> dict[str, tuple[int, str]]:
    """Each item's stored context sentences (page text), rendered `e<encounter>`."""
    out = {}
    for item in item_ids:
        for r in s.store.all("SELECT e.id, e.context_sentence FROM encounters e JOIN knowledge_items k ON "
                             "k.id = e.knowledge_item_id WHERE k.id=? AND k.learner_id=? AND e.context_sentence != '' "
                             "ORDER BY e.id DESC LIMIT 3", (item, s.learner_id)):
            out[f"e{r['id']}"] = (item, r["context_sentence"])
    return out


def _card_items(s, sel) -> list[tuple[int, str]]:
    ids = list(sel.get("item_ids") or ())
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [(r["id"], r["key"]) for r in s.store.all(
        f"SELECT id, key FROM knowledge_items WHERE id IN ({marks}) AND learner_id=? ORDER BY id", (*ids, s.learner_id))]


def add_cards_sections(s, sel) -> tuple[Section, ...] | Rejected:
    items = _card_items(s, sel)
    ctx = _contexts(s, [i for i, _ in items])
    if not items or not ctx:
        return Rejected("no cards to add")
    return (_section("page", [Leaf(f"{rid} (for i{item}): {text}", book=True)
                              for rid, (item, text) in ctx.items()]),
            _section("cycle", [Leaf(f"i{i} '{k}'", book=True) for i, k in items]))


def add_cards_check(s, sel, value: schemas.AddCardsContent) -> dict | Rejected:
    items = dict(_card_items(s, sel))
    ctx = _contexts(s, list(items))
    cards: dict[int, dict] = {}
    for c in value.cards:
        item = int(c.item_id[1:]) if c.item_id[:1] == "i" and c.item_id[1:].isdigit() else None
        hit = ctx.get(c.sentence)
        if item not in items or item in cards or hit is None or hit[0] != item:
            continue
        if not set(_norms(items[item])) <= set(_norms(c.front)) or not phrases.safe(c.back):
            continue  # the front names the item; the back passes the deny-list
        cards[item] = {"front": c.front.strip(), "back": c.back.strip(), "sentence": hit[1]}
    return {"cards": cards} if cards else Rejected("no cards to add")


prompts.TASKS.update({
    "quiz": "Write short comprehension questions about the sentences in <page>. Each question cites the sentence "
            "ids it rests on in `evidence`. For completion, recall and wh- questions give `answers` as keyword "
            "sets, every word of every set taken from the cited sentences; open-ended and distancing questions "
            "have no answers. Cite an item id only when its word is in the question, its answers or its "
            "sentences.",
    "read_aloud": "The harness will read the sentences in <page> aloud. Give a simple Chinese translation of "
                  "them in `translate` (or an empty string), and up to three sentence ids that are hard enough "
                  "to read slowly.",
    "add_cards": "Write one Anki card per item in <cycle>: `front` names the item, `back` explains it simply in at "
                 "most 200 characters, `sentence` is the id of one of that item's sentences in <page>.",
})
GENERATORS.update({
    "quiz": Generator(schemas.QuizContent, quiz_sections, quiz_check),
    "read_aloud": Generator(schemas.ReadAloudContent, read_aloud_sections, read_aloud_check),
    "add_cards": Generator(schemas.AddCardsContent, add_cards_sections, add_cards_check),
})
