"""New items, teaching and recall (ADR-0017 §3.1, §3.4, §6.2; M7 design D15, D17 and its ranking, O5, O6). The
harness test (R11) runs a real World end to end: a page read, a ranked new item taught with Brain content, and the
same item offered for recall on the next household day. Real Store and Inputs, a mock Brain; nothing speaks."""

from __future__ import annotations

import datetime as dt

from leafi.core.storage import Store
from leafi.core.wordinfo import TableWordInfo
from leafi.services.brain.mock import MockModel
from leafi.study import item_status, items, knowledge
from leafi.study.brain import call as bc
from leafi.study.brain import kinds, schemas
from leafi.study.harness.construct import construct
from leafi.study.harness.menu import allowed
from leafi.study.harness.state import Activity, Rejected, Spec
from tests import seed
from tests.harness_world import make_world, run

WORDS = TableWordInfo(["fox", "ran", "home", "late", "dark", "moon", "slept"])
LINES = ["The fox ran home.", "It was late and dark."]


def _status(store, item):
    return store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"]


def _key(store, item):
    return store.one("SELECT key FROM knowledge_items WHERE id=?", (item,))["key"]


# ---------------------------------------------------------------- ranking


def test_one_unknown_sentences_come_first_and_known_words_are_never_candidates(settings):
    store = Store(settings.db_path)
    learner = seed.learner(store)
    for word, status in (("fox", "known"), ("ran", "ignored"), ("late", "learning")):
        item = knowledge.upsert_item(store, learner, "word", word)
        store.execute("UPDATE knowledge_items SET status=? WHERE id=?", (status, item))
    got = items.new_candidates(store, learner, LINES, WORDS, 5)
    # "The fox ran home." has one unknown word (home); "late" counts as unknown (O6) but is not new, so "dark"'s
    # sentence has two unknowns and comes after; function words ("the", "it", "was", "and") are never candidates
    assert [_key(store, i) for i in got] == ["home", "dark"]
    assert items.new_candidates(store, learner, LINES, WORDS, 1) == got[:1]
    assert items.new_candidates(store, learner, LINES, WORDS, 0) == []


def test_an_item_row_is_made_only_for_the_words_chosen_and_the_band_orders_ties(settings):
    store = Store(settings.db_path)
    learner = seed.learner(store)

    class Banded(TableWordInfo):
        def band(self, w):
            return 0 if w in ("dark", "late") else 1

    info = Banded(WORDS._words)
    got = items.new_candidates(store, learner, ["The fox ran home and it was late and dark."], info, 2)
    assert [_key(store, i) for i in got] == ["late", "dark"]  # the children's-book band first
    assert store.one("SELECT COUNT(*) AS n FROM knowledge_items")["n"] == 2


def test_the_card_check_counts_lapsed_as_unknown_too(settings):
    from leafi.study import cards

    store = Store(settings.db_path)
    learner = seed.learner(store)
    fox = knowledge.upsert_item(store, learner, "word", "fox")
    home = knowledge.upsert_item(store, learner, "word", "home")
    store.execute("UPDATE knowledge_items SET status='lapsed' WHERE id=?", (home,))
    verdict, _ = cards.check(store, learner, fox, {"背面": "an animal"}, "The fox ran home.")
    assert verdict == "flag"  # O6: one notion of unknown for ranking and cards


# ---------------------------------------------------------------- the teach_items generator (D15)


def _brain(w, reply):
    model = MockModel({"generate": reply})
    w.s.brain = bc.Brain({"fast": [], "standard": [(model, "mock-model")], "deep": []},
                         locality=lambda backend, m: "local")
    return model


async def _read(settings, script):
    w = make_world(settings, settings, [*LINES, *script], word_info=WORDS)
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    return w


def _teach(item, **kw):
    return {"item_id": f"i{item}", "method": "explain", "explanation": "Home is where you live.",
            "prompt": "What is the word for where you live?", "expect": "item_said", **kw}


async def test_teach_content_is_bound_to_the_selection_once_and_a_cloze_never_gives_the_word_away(settings):
    w = await _read(settings, [])
    home, dark = (knowledge.upsert_item(w.store, w.s.learner_id, "word", k) for k in ("home", "dark"))
    sel = {"item_ids": [home, dark]}
    value = schemas.TeachItemsContent(items=[
        schemas.TeachItem(**_teach(home)),
        schemas.TeachItem(**_teach(home, prompt="again")),                       # duplicate: dropped
        schemas.TeachItem(**_teach(999)),                                         # not selected: dropped
        schemas.TeachItem(**_teach(dark, expect="cloze_word", prompt="It was ___ and dark.")),  # gives it away
        schemas.TeachItem(**_teach(dark, expect="cloze_word", prompt="It was late and ___.")),
    ])
    out = kinds.teach_check(w.s, sel, value)
    assert [(t["item_id"], t["expect"]) for t in out["items"]] == [(home, "item_said"), (dark, "cloze_word")]
    assert [t["sentence"] for t in out["items"]] == ["The fox ran home.", "It was late and dark."]
    assert out["items"][1]["prompt"] == "It was late and ___."  # the give-away cloze was dropped
    bad = schemas.TeachItemsContent(items=[schemas.TeachItem(**_teach(home, explanation="That was a stupid guess."))])
    assert isinstance(kinds.teach_check(w.s, sel, bad), Rejected)  # the deny-list


async def test_i_know_this_word_ignores_the_item_and_scores_nothing(settings):
    w = await _read(settings, ["I know this word"])
    home = knowledge.upsert_item(w.store, w.s.learner_id, "word", "home")
    assert home in w.facts().new_item_candidates
    content = {"items": [{"item_id": home, "key": "home", "method": "explain", "explanation": "Where you live.",
                          "prompt": "Say the word for where you live.", "expect": "item_said",
                          "sentence": "The fox ran home."}]}
    status, outcome, _ = await run(w, "teach_items", {"item_ids": [home]}, content=content, content_owner="brain")
    assert status == "completed" and outcome == {"items": 1, "results": ["known"]}
    assert _status(w.store, home) == "ignored"
    ev = w.store.one("SELECT event, source, session_id FROM item_status_events")
    assert tuple(ev) == ("ignore", "learner", w.s.session_id)
    assert w.store.one("SELECT COUNT(*) AS n FROM retrieval_events")["n"] == 0
    assert home not in w.facts().new_item_candidates


# ---------------------------------------------------------------- the harness test (R11)


async def test_a_page_read_teaches_a_ranked_new_item_and_recalls_it_the_next_household_day(settings, monkeypatch):
    w = await _read(settings, ["home", "home"])
    for word in ("fox", "ran"):  # already known: "home" is then the one unknown word of its sentence
        item = knowledge.upsert_item(w.store, w.s.learner_id, "word", word)
        w.store.execute("UPDATE knowledge_items SET status='known' WHERE id=?", (item,))
    f = w.facts()
    assert "teach_items" not in allowed(w.s)  # Brain-owned content and no Brain yet (S6)
    home = f.new_item_candidates[0]
    assert _key(w.store, home) == "home" and _status(w.store, home) == "new"
    model = _brain(w, lambda req: {"items": [_teach(home)]})
    assert "teach_items" in allowed(w.s)
    a = await construct(w.s, Spec("teach_items", {"item_ids": [home]}), allowed(w.s))
    assert isinstance(a, Activity) and model.requests[0].purpose == "generate"
    status, outcome, _ = await run(w, "teach_items", a.params, content=a.content, content_owner="brain")
    assert status == "completed" and outcome == {"items": 1, "results": ["success"]}
    enc = w.store.one("SELECT trigger, context_sentence, explanation_en FROM encounters WHERE knowledge_item_id=?",
                      (home,))
    assert tuple(enc) == ("teach_ok", "The fox ran home.", "Home is where you live.")
    assert _status(w.store, home) == "learning"
    assert w.facts().recall_due == ()  # due one household day after the first event

    tomorrow = (dt.date.fromisoformat(item_status.household_day(settings.household_tz)) + dt.timedelta(days=1))
    monkeypatch.setattr(item_status, "household_day", lambda tz="", when=None: tomorrow.isoformat())
    assert w.facts().recall_due == (home,)
    assert "recall_items" in allowed(w.s)
    r = await construct(w.s, Spec("recall_items", {"item_ids": [home]}), allowed(w.s))
    assert isinstance(r, Activity) and r.content_owner == "code"
    status, outcome, _ = await run(w, "recall_items", r.params)
    assert status == "completed" and outcome == {"items": 1, "results": ["success"]}
    days = [r["day"] for r in w.store.all("SELECT day FROM retrieval_events ORDER BY id")]
    assert days == [(tomorrow - dt.timedelta(days=1)).isoformat(), tomorrow.isoformat()]
    assert w.facts().recall_due == ()  # the success moved it two days on
