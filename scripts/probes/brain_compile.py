"""The M7 compilation probe (M7 design D6, step M7b): one real call per Brain schema, before sessions call Claude.

    .venv\\Scripts\\python scripts/probes/brain_compile.py

Every schema goes once to the fast tier's model, then the smallest one once to each configured tier, so a wrong model
id shows here and not in a session. The requests hold only invented text (a made-up page and answer) and go through
`leafi.privacy.egress` like a session's. Egress attributes every study call to a learner, so the probe runs on a
throwaway database in a temporary folder with an invented learner: `data/leafi.db` is never opened. Costs a few cents.
Speaks nowhere. Exit 0 only when every call parsed into its model.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from leafi import bootstrap  # noqa: E402
from leafi.core.config import Settings  # noqa: E402
from leafi.core.ports import CallAttempt, Leaf, Section  # noqa: E402

PAGE = ("Mia found a small green frog by the pond. It hopped onto her boot. "
        "\"You are brave,\" she whispered. The frog blinked and jumped back into the water.")
TIMEOUT_S = 60.0


def _cases():
    from leafi.study.brain import prompts, schemas

    page = Section("page", (Leaf(PAGE, book=True),))
    gen = dict(policy=prompts.policy_text(autonomy=2, age_band="7-9"), learner_id=None, session_id=None)
    one = dict(learner_id=None, session_id=None)
    menu = Section("menu", (Leaf("read_listen, practise_errors, quiz, break, end"),))
    yield "decide", schemas.Decision, prompts.decide_request((page, menu), **gen)
    for kind, model in (("teach_items", schemas.TeachItemsContent), ("quiz", schemas.QuizContent),
                        ("read_aloud", schemas.ReadAloudContent), ("add_cards", schemas.AddCardsContent),
                        ("notes", schemas.NotesContent), ("book_note", schemas.BookNoteContent)):
        yield f"generate:{kind}", model, prompts.generate_request(kind, (page,), model, **gen)
    question = Section("question", (Leaf("Why did the frog jump back?"),))
    yield "answer", schemas.AnswerContent, prompts.single_request(
        "answer", prompts.ANSWER_SYSTEM, (page, question), schemas.AnswerContent, **one)
    yield "judge", schemas.Judgement, _judge(**one)


def _judge(**one):
    from leafi.study.brain import prompts, schemas

    sections = (Section("word", (Leaf("brave", book=True),)), Section("prompt", (Leaf("Use 'brave' in a sentence."),)),
                Section("answer", (Leaf("The firefighter was brave in the fire."),)))
    return prompts.single_request("judge", prompts.JUDGE_SYSTEM, sections, schemas.Judgement, **one)


async def _one(label: str, backend, model_name: str, tier: str, pyd, make) -> bool:
    req = make(model_name, tier, [], None, CallAttempt(), TIMEOUT_S)
    rec = await backend.call(req)
    ok = rec.outcome == "ok"
    note = rec.detail or ""
    if ok:
        try:
            pyd.model_validate(rec.value)
        except Exception as e:  # noqa: BLE001 - reported, not raised
            ok, note = False, f"pydantic: {type(e).__name__}"
    print(f"{'ok ' if ok else 'BAD'} {tier:8} {model_name:22} {label:22} {rec.outcome:10} "
          f"{rec.latency_ms:6} ms  in {rec.tokens_in:5} out {rec.tokens_out:5}  {note}")
    return ok


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="leafi-probe-") as tmp:
        settings = Settings(data_dir=Path(tmp))
        bootstrap.install(settings)
        if not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY is empty: nothing to probe")
            return 2
        from leafi.core import learner_store
        from leafi.core.storage import Store
        from leafi.privacy import runtime

        with Store(settings.db_path) as store:
            learner = learner_store.create(store, "Probe")
        egress = runtime.get(settings)
        egress.start_detector()
        await asyncio.to_thread(egress._det_done.wait, 120)  # inside a session it refuses learner text while loading
        try:
            with runtime.attributed(learner):
                return await _probe(settings, egress)
        finally:
            runtime.get(settings).close()


async def _probe(settings, egress) -> int:
    from leafi import app

    brain = app.build_brain(settings, egress)
    if brain is None:
        print("no usable Brain tier (leafi doctor → brain tiers)")
        return 2
    tiers = {t: entries[0] for t, entries in brain.tiers.items() if entries}
    first = next(iter(tiers))
    backend, model_name = tiers[first]
    results = [await _one(label, backend, model_name, first, pyd, make) for label, pyd, make in _cases()]
    _, pyd, make = list(_cases())[-1]
    for tier, (b, m) in tiers.items():
        if tier != first:
            results.append(await _one("judge", b, m, tier, pyd, make))
    print(f"{sum(results)}/{len(results)} ok")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
