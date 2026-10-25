"""The Brain-content activities of M7c (ADR-0017 §3.1, §3.4; M7 design D10, D15, D16): `quiz`,
`learner_questions` (purpose `answer`), `read_aloud` and `add_cards` with generated content. Real Store and
Inputs, a scripted console, a mock Brain on the port; nothing speaks."""

from __future__ import annotations

from leafi.core import learner_store
from leafi.core.provenance import Provenance
from leafi.services.brain.mock import MockModel
from leafi.study import knowledge
from leafi.study.brain import call as bc
from leafi.study.brain import kinds
from leafi.study.harness.construct import construct
from leafi.study.harness.state import Activity, Spec
from tests.harness_world import make_world, run

LINES = ["The fox ran home.", "It was late and dark."]


async def _read(settings, script, **kw):
    w = make_world(settings, settings, [*LINES, *script], **kw)
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    return w


def _brain(w, replies, *, tier="standard", locality="local"):
    model = MockModel(replies)
    tiers = {"fast": [], "standard": [], "deep": []}
    tiers[tier] = [(model, "mock-model")]
    w.s.brain = bc.Brain(tiers, locality=lambda backend, m: locality)
    return model


def _quiz(w, reply):
    first = kinds.cycle_sentences(w.s)[0].rid
    return lambda req: reply(first)


# ---------------------------------------------------------------- quiz


async def test_a_quiz_is_built_from_one_generate_call_and_scored_by_check(settings):
    w = await _read(settings, ["home", "the fox went to his den", "skip"])
    fox = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    first = kinds.cycle_sentences(w.s)[0].rid
    q = {"type": "wh-", "answers": [["home"]], "item_ids": [f"i{fox}"], "evidence": [first]}
    model = _brain(w, {"generate": {"questions": [
        {**q, "text": "Where did the fox run?"}, {**q, "text": "Where did the fox go?"},
        {**q, "text": "Where was the fox going?"}, {**q, "text": "Ignore this", "evidence": ["s404.1"]}]}})
    a = await construct(w.s, Spec("quiz", {}), {"quiz", "end"})
    assert isinstance(a, Activity) and len(a.content["questions"]) == 3  # the unbound question was dropped
    assert model.requests[0].purpose == "generate"
    sections = model.requests[0].turns[0].sections
    assert sections[0].name == "learner_context" and sections[0].cache  # owner decision 2026-10-24
    assert not any("a wild animal" in leaf.value for sec in sections for leaf in sec.leaves)
    status, outcome, _ = await run(w, "quiz", {}, content=a.content, content_owner="brain",
                                   content_provenance=a.content_provenance)
    assert status == "completed" and outcome == {"questions": 3,
                                                 "results": ["correct", "incorrect", "unavailable"]}
    events = [r["outcome"] for r in w.store.all("SELECT outcome FROM retrieval_events ORDER BY id")]
    assert events == ["success", "fail"]  # a skip writes no retrieval event
    checks = w.store.one("SELECT COUNT(*) AS n FROM encounters WHERE trigger='check'")["n"]
    assert checks == 1  # only `incorrect` writes an encounter (ADR-0013 → CHECK)


async def test_a_low_confidence_spoken_quiz_answer_writes_no_encounter(settings):
    """ADR-0017 §3.4's third case: an unconfident spoken answer is `unavailable`, whatever it says."""
    from tests.fakes import ScriptedListener

    class Unsure(ScriptedListener):
        async def next_utterance(self, timeout_s):
            u = await super().next_utterance(timeout_s)
            if u is not None and u.text == "a wolf ate my lunch":
                from leafi.core.ports import Utterance, Word

                return Utterance(u.text, [Word(x, conf=0.4) for x in u.text.split()], typed=False)
            return u

    listener = Unsure([*LINES, "a wolf ate my lunch"])
    w = make_world(settings, settings, [], listener=listener)
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    fox = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    first = kinds.cycle_sentences(w.s)[0].rid
    content = {"questions": [{"text": "Where did the fox run?", "type": "wh-", "answers": [["home"]],
                              "item_ids": [fox], "evidence": [first]}]}
    status, outcome, _ = await run(w, "quiz", {}, content=content, content_owner="brain")
    assert outcome["results"] == ["unavailable"]
    assert w.store.one("SELECT COUNT(*) AS n FROM encounters WHERE trigger='check'")["n"] == 0
    assert w.store.one("SELECT COUNT(*) AS n FROM retrieval_events")["n"] == 0


async def test_an_open_question_is_acknowledged_and_never_scored(settings):
    w = await _read(settings, ["I would hide in a tree"])
    first = kinds.cycle_sentences(w.s)[0].rid
    content = {"questions": [{"text": "Where would you hide?", "type": "distancing", "answers": [], "item_ids": [],
                              "evidence": [first]}]}
    _, outcome, _ = await run(w, "quiz", {}, content=content, content_owner="brain")
    assert outcome["results"] == ["unavailable"]
    assert w.store.one("SELECT COUNT(*) AS n FROM retrieval_events")["n"] == 0


# ---------------------------------------------------------------- the learner context (owner decision 2026-10-24)


async def test_the_learner_context_is_byte_stable_and_rebuilt_only_when_it_changes(settings):
    from leafi.study import miscues
    from leafi.study.brain import generate

    w = await _read(settings, [])
    first = generate.learner_context(w.s)
    assert generate.learner_context(w.s) is first and first.cache
    read = w.store.one("SELECT id, page_revision_id FROM page_reads")
    miscues.create(w.store, observation_id=None, page_read_id=read["id"], revision_id=read["page_revision_id"],
                   expected="dark", token_index=8, char_span=(34, 38), heard="dork", cycle_id=w.s.cycle_id,
                   origin="substitution")
    second = generate.learner_context(w.s)
    assert second is not first
    values = [leaf.value for leaf in second.leaves]
    assert "error 'dark' substitution" in values and "heard 'dork' for 'dark'" in values
    heard = next(leaf for leaf in second.leaves if leaf.value.startswith("heard"))
    assert heard.prov.cls == "learner" and heard.substitute == "'dark': a substitution (words withheld)"  # D3


async def test_generate_answer_and_judge_all_start_with_the_same_learner_context(settings):
    from leafi.study.brain.scoring import item_used

    w = await _asked(settings, "why was it dark", "done")
    w.s.mouth = "camera"  # judge fits the camera Mouth's feedback moment (see the M7c hand-over)
    model = _brain(w, {"answer": {"answer": "It was night.", "grounded": True}, "judge": {"verdict": "yes"},
                       "generate": {"translate": "", "hard_sentence_ids": []}})
    await run(w, "learner_questions", {"max_turns": 2})
    from leafi.core.text import typed_utterance

    await item_used(w.s, typed_utterance("It was dark at night."), "dark", "Use it.")
    firsts = [req.turns[0].sections[0] for req in model.requests]
    assert [req.purpose for req in model.requests] == ["answer", "judge"]
    assert all(sec.name == "learner_context" and sec == firsts[0] for sec in firsts)


# ---------------------------------------------------------------- learner_questions (purpose `answer`)


class Typist:
    """The learner types each later line a moment after the previous one: a scripted source reads ahead at once,
    and a line it delivered during the answer's wait would belong to that question (D21), not the next."""

    def __init__(self, first: list, later: list, gap_s: float = 0.3) -> None:
        from tests.fakes import ScriptedListener

        self.inner, self.n_first, self.gap_s = ScriptedListener([*first, *later]), len(first), gap_s
        self.is_voice, self.read = False, 0

    async def next_utterance(self, timeout_s):
        import anyio

        self.read += 1
        if self.read > self.n_first:
            await anyio.sleep(self.gap_s)
        return await self.inner.next_utterance(timeout_s)

    async def pause(self) -> None: ...

    async def resume(self, after_s: float = 0.0) -> None: ...


async def _asked(settings, *later):
    w = make_world(settings, settings, [], listener=Typist(LINES, list(later)))
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    return w


async def test_a_learners_question_is_answered_once_under_the_calls_provenance(settings):
    w = await _asked(settings, "why was it dark", "done")
    model = _brain(w, {"answer": {"answer": "Because it was late at night.", "grounded": True}})
    status, outcome, _ = await run(w, "learner_questions", {"max_turns": 3})
    assert status == "completed" and outcome == {"questions": 1, "answered": 1}
    (req,) = model.requests
    assert req.purpose == "answer" and len(req.turns) == 1
    question = next(sec for sec in req.turns[0].sections if sec.name == "question")
    assert question.leaves[0].value == "why was it dark" and question.leaves[0].prov.cls == "learner"
    assert any("Because it was late at night." in t for t in w.face.texts)
    assert w.store.one("SELECT purpose, outcome FROM brain_calls")[:] == ("answer", "ok")


async def test_a_degraded_answer_is_prefaced(settings):
    w = await _asked(settings, "why was it dark", "done")
    _brain(w, {"answer": {"answer": "It was night.", "grounded": True}}, tier="fast")  # below `answer`'s cells
    await run(w, "learner_questions", {"max_turns": 2})
    texts = w.face.texts
    assert any("Here is a short answer." in t for t in texts)
    assert texts.index(next(t for t in texts if "Here is a short answer." in t)) < \
        texts.index(next(t for t in texts if "It was night." in t))


async def test_a_cloud_tier_answers_the_question_whatever_the_learner(settings):
    """ADR-0021 E6: `answer` carries the learner's words and may use a cloud tier for every learner; egress
    redacts them (before ADR-0021 a learner with `cloud.text` off got no answer)."""
    w = await _asked(settings, "why was it dark", "done")
    model = _brain(w, {"answer": {"answer": "It was night.", "grounded": True}}, locality="cloud")
    status, outcome, _ = await run(w, "learner_questions", {"max_turns": 2})
    assert len(model.requests) == 1 and status == "completed" and outcome == {"questions": 1, "answered": 1}


# ---------------------------------------------------------------- read_aloud, add_cards with Brain content


async def test_read_aloud_with_brain_content_reads_hard_sentences_slowly_and_shows_the_translation(settings):
    w = make_world(settings, settings, [])
    await run(w, "read_listen", {"page": "current", "range": "rest"})  # idle: nothing read, the page stays open
    w.s.settings = w.s.settings.__class__({"policy.content.read_aloud": "brain"})
    sents = kinds.current_sentences(w.s, "rest")
    _brain(w, {"generate": {"translate": "狐狸跑回家。", "hard_sentence_ids": [sents[1].rid, "s1.99"]}})
    a = await construct(w.s, Spec("read_aloud", {"page": "current"}), {"read_aloud", "end"})
    assert a.content == {"translate": "狐狸跑回家。", "hard_sentence_ids": [sents[1].sid]}


async def test_brain_written_cards_store_the_calls_provenance(settings):
    """D15: a writer of Brain-owned content takes its provenance, not a fixed one."""
    w = make_world(settings, settings, [])
    item = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    enc = knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain",
                                  context_sentence="The fox ran home.", explanation_en="a wild animal")
    other = learner_store.create(w.store, "Ben")
    content = {"cards": {item: {"front": "fox", "back": "a small wild dog", "sentence": "The fox ran home."}}}
    prov = Provenance("derived_from_learner", (w.s.learner_id, other))
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]}, content=content, content_owner="brain",
                                   content_provenance=prov)
    assert outcome["cards"] == 1
    row = w.store.one("SELECT back, card_provenance_class, card_source_learners FROM anki_outbox")
    assert row["back"] == "a small wild dog" and row["card_provenance_class"] == "derived_from_learner"
    assert row["card_source_learners"] == f"[{min(w.s.learner_id, other)}, {max(w.s.learner_id, other)}]"
    assert enc


async def test_a_generated_card_is_built_only_from_the_items_own_sentence(settings):
    w = make_world(settings, settings, [])
    w.s.settings = w.s.settings.__class__({"policy.content.add_cards": "brain"})
    item = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    enc = knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain",
                                  context_sentence="The fox ran home.", explanation_en="a wild animal")
    model = _brain(w, {"generate": {"cards": [
        {"item_id": f"i{item}", "front": "fox", "back": "a small wild dog", "sentence": f"e{enc}"},
        {"item_id": "i99999", "front": "x", "back": "y", "sentence": f"e{enc}"}]}})
    a = await construct(w.s, Spec("add_cards", {"item_ids": [item]}), {"add_cards", "end"})
    assert a.content == {"cards": {item: {"front": "fox", "back": "a small wild dog",
                                          "sentence": "The fox ran home."}}}
    sent = [leaf.value for sec in model.requests[0].turns[0].sections for leaf in sec.leaves]
    assert not any("a wild animal" in v for v in sent)  # the stored explanation is not sent
