"""ADR-0017 §3.1 / §8 and ADR-0013 on the harness activities (M6d). Never mocked: real Store, scripted console."""

from __future__ import annotations

from leafi.study.harness import rows
from tests.harness_world import PAGE_2, candidates, make_world, run


async def test_read_listen_creates_cycle_owned_candidates_and_practises_nothing_inside_reading(settings):
    w = make_world(settings, settings, ["The fox ran home.", "It was late and dork."])
    status, outcome, aid = await run(w, "read_listen", {"page": "next"})
    assert status == "completed" and outcome["sentences"] == 2
    cyc = w.store.one("SELECT cycle_id FROM activities WHERE id=?", (aid,))["cycle_id"]
    assert cyc == w.s.cycle_id and candidates(w) == {"dark": ("candidate", None, cyc)}
    said = [t for t in w.face.texts]
    assert not any("practise" in t.lower() or "try" in t.lower() for t in said)  # no practice inside reading
    assert not any(t in ("Nice!", "Smooth.", "Got it.") for t in said)  # no sentence_done line


async def test_a_page_turn_ends_page_turned_and_a_continuation_reads_the_next_page_in_the_same_cycle(settings, tmp_path):
    p2 = tmp_path / "p2.txt"
    p2.write_text(PAGE_2, encoding="utf-8")
    w = make_world(settings, settings, ["The fax ran home.", f"/page 2 --text {p2}", "The moon was up.",
                                        "The fox slept."])
    status, _, first = await run(w, "read_listen", {"page": "next"})
    assert status == "page_turned"
    cyc = w.s.cycle_id
    assert candidates(w)["fox"] == ("candidate", None, cyc)  # completed nothing, settled nothing
    status, _, cont = await run(w, "read_listen", {"page": "next"}, continuation=True)
    assert status == "completed"
    row = w.store.one("SELECT cycle_id, continuation FROM activities WHERE id=?", (cont,))
    assert (row["cycle_id"], row["continuation"]) == (cyc, 1)
    assert w.store.one("SELECT COUNT(*) AS n FROM cycles")["n"] == 1
    assert w.store.one("SELECT COUNT(DISTINCT page_id) AS n FROM page_reads WHERE cycle_id=?", (cyc,))["n"] == 2


async def test_turning_back_within_a_cycle_resumes_that_page_read(settings, tmp_path):
    p1, p2 = tmp_path / "p1.txt", tmp_path / "p2.txt"
    p2.write_text(PAGE_2, encoding="utf-8")
    p1.write_text("The fox ran home. It was late and dark.", encoding="utf-8")
    w = make_world(settings, settings, ["The fox ran home.", f"/page 2 --text {p2}", f"/page 1 --text {p1}",
                                        "It was late and dark."])
    await run(w, "read_listen", {"page": "next"})
    first_read = w.read_id
    status, _, _ = await run(w, "read_listen", {"page": "next"}, continuation=True)
    assert status == "page_turned"
    status, outcome, _ = await run(w, "read_listen", {"page": "next"}, continuation=True)
    assert status == "completed" and w.read_id == first_read and outcome["sentences"] == 1


async def test_skip_completes_the_current_sentence(settings):
    w = make_world(settings, settings, ["/skip", "It was late and dark."])
    status, outcome, _ = await run(w, "read_listen", {"page": "next"})
    assert status == "completed" and w.state.page_complete()
    assert len(w.s.latch.skips) == 0  # consumed exactly once


async def test_text_mode_silence_is_idle_session(settings):
    w = make_world(settings, settings, [None])
    status, _, _ = await run(w, "read_listen", {"page": "next"})
    assert status == "idle_session" and w.s.latch.terminal == "idle_session"


async def test_a_page_turn_during_the_second_candidate_leaves_it_and_the_third_owned_by_the_cycle(settings):
    """libraries §7 flow steps 1-3: three candidates, practice, a page turn mid-practice."""
    w = make_world(settings, settings, ["The fax ran car.", "It was lit and dark.",  # fox, home, late
                                        "fox",                                       # fox: pass
                                        "/next"])                                    # turn during home
    await run(w, "read_listen", {"page": "next"})
    cands = {r["expected"]: r["id"] for r in w.store.all("SELECT id, expected FROM miscues")}
    assert set(cands) == {"fox", "home", "late"}
    status, outcome, _ = await run(w, "practise_errors", {"candidate_ids": [cands["fox"], cands["home"],
                                                                              cands["late"]]})
    assert status == "page_turned"
    c = candidates(w)
    assert c["fox"][:2] == ("withdrawn", "practice")
    assert c["home"][0] == c["late"][0] == "candidate"  # still owned by the cycle (ADR-0017 §8.2)
    assert w.store.one("SELECT COUNT(*) AS n FROM practices WHERE miscue_id=?", (cands["home"],))["n"] == 0


async def test_a_later_practise_errors_continues_with_the_next_attempt_number(settings):
    w = make_world(settings, settings, ["The fax ran home.", "It was late and dark.", "box", "/page 2",
                                        "fix", ])
    await run(w, "read_listen", {"page": "next"})
    mid = w.store.one("SELECT id FROM miscues WHERE expected='fox'")["id"]
    status, _, _ = await run(w, "practise_errors", {"candidate_ids": [mid]})
    assert status == "page_turned"
    assert [r["attempt"] for r in w.store.all("SELECT attempt FROM practices WHERE miscue_id=?", (mid,))] == [1]
    status, _, _ = await run(w, "practise_errors", {"candidate_ids": [mid]})
    assert status == "completed"
    assert [(r["attempt"], r["outcome"]) for r in w.store.all(
        "SELECT attempt, outcome FROM practices WHERE miscue_id=? ORDER BY attempt", (mid,))] == \
        [(1, "disagreed"), (2, "disagreed")]
    assert candidates(w)["fox"][:2] == ("unsure", "disagreed")


async def test_skip_and_idle_in_practice(settings):
    w = make_world(settings, settings, ["The fax ran car.", "It was late and dark.", "/skip", None])
    await run(w, "read_listen", {"page": "next"})
    ids = [r["id"] for r in w.store.all("SELECT id FROM miscues ORDER BY id")]
    await run(w, "practise_errors", {"candidate_ids": ids})
    c = candidates(w)
    assert c["fox"][:2] == ("unsure", "skipped") and c["home"][:2] == ("unsure", "idle")


async def test_closing_the_cycle_settles_unpractised_candidates(settings):
    w = make_world(settings, settings, ["The fax ran home.", "It was late and dark."])
    await run(w, "read_listen", {"page": "next"})
    rows.close_cycle(w.store, w.s.cycle_id, "wrap")
    assert candidates(w)["fox"][:2] == ("unsure", "not_practised")


async def test_review_grades_eases_1_to_4_and_writes_retrieval_events(settings):
    from leafi.core.storage import now_iso
    from leafi.study import anki, knowledge
    from tests.fakes.anki import FakeAnki

    fake = FakeAnki()
    w = make_world(settings, settings, ["/hard", "again", "/skip"], anki=anki.AnkiClient(transport=fake.transport()))
    items = []
    for key in ("fox", "moon", "dark"):
        item = knowledge.upsert_item(w.store, w.s.learner_id, "word", key)
        cid = fake.add_due_card(key)
        nid = fake.cards[cid]["note"]
        w.store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=?, updated_at=? WHERE knowledge_item_id=?",
                        (nid, now_iso(), item))
        items.append(item)
    await w.refresh()
    assert w.facts().anki_due == 3
    status, outcome, aid = await run(w, "review_anki", {"max_cards": 3})
    assert status == "completed" and outcome["cards"] == 2  # the third was skipped
    eases = [r["ease"] for r in w.store.all("SELECT ease FROM review_answers ORDER BY id")]
    assert eases == [2, 1]
    ev = [(r["item_id"], r["outcome"], r["evidence"]) for r in w.store.all(
        "SELECT item_id, outcome, evidence FROM retrieval_events ORDER BY id")]
    assert ev == [(items[0], "success", "typed"), (items[1], "fail", "typed")]


async def test_a_new_cycle_opens_the_page_where_the_learner_stopped_mapped_through_a_correction(settings):
    """ADR-0013 → Opening a page read, range `rest`: the previous ccur is mapped through the edit maps; tokens a
    correction touched before it are `unread`."""
    from leafi.study import corrections, pages

    w = make_world(settings, settings, ["The fox ran home.", "/next"])
    await run(w, "read_listen", {"page": "next"})
    page = w.page_id
    rows.close_cycle(w.store, w.s.cycle_id, "wrap")  # a closed cycle's page read keeps its revision
    w.s.cycle_id = None
    rev = pages.current_revision(w.store, page)
    span = corrections.locate(rev.text, "fox")
    corrections.apply_correction(w.store, page_id=page, revision_id=rev.id, char_start=span[0], char_end=span[1],
                                 new_text="red fox", source="parent", learner_id=None)
    w.pending = None
    status = (await run(w, "read_listen", {"page": "current"}))[0]  # the script ended: /stop
    assert status == "stopped"
    st = w.state
    assert st.statuses().split() == ["C", "R", "R", "C", "C", "U", "U", "U", "U", "U"]
    assert (st.pcur, st.ccur, st.completed) == (5, 5, {1})


async def test_read_aloud_break_wait_and_end(settings):
    w = make_world(settings, settings, ["/skip", "read"])
    status, outcome, _ = await run(w, "read_aloud", {"page": "next"})
    assert status == "completed" and outcome["sentences"] == 2
    assert "The fox ran home." in w.face.texts
    status, _, _ = await run(w, "break", {"seconds": 5})
    assert status == "skipped"
    status, _, _ = await run(w, "wait", {"seconds": 5})
    assert status == "completed"  # any input ends a wait, so the learner can choose
    assert (await run(w, "end", {}))[0] == "completed"
