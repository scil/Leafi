Design round 1. Review **revision 1** of `docs/plans/active/2026-10-25-study-session-panel-design.md` as a design,
not as prose. Its plan is `docs/plans/active/2026-10-25-study-session-panel.md`; its research is
`docs/research/2026-10-25-session-panel.md`. The owner's choices are fixed and out of scope: the study process hosts
the endpoint inside a device adapter that the web UI proxies (C1(a)); a panel answer moves the session but must be
told apart from the child's own (C2(a)); loopback only.

1. Check the design's claims against the code as it is: `leafi/study/harness/inputs.py` (`Inputs.__init__`, `start`,
   `_reader`, `_deliver`, `_listener_lost`, `listen`, `_speak`, `controls_only`), `leafi/study/harness/latch.py`
   (`post_skip`, `take_skip`, `drain_skips`, `epoch`), `leafi/study/harness/negotiate.py` (`negotiate`, the `wanted`
   path, `parse_choice`), `leafi/study/harness/world.py` (`activity_over`, `end_page_read`),
   `leafi/study/harness/activities.py` (`_confident`, `read_listen`, `_reading_utterance`, `practise_errors`,
   `review_anki`, `quiz`, `_ask_item`, `learner_questions`), `leafi/study/harness/loop.py` (`Env.on_built`,
   `run_session`, `_body`, `run_activity`), `leafi/study/controls.py`, `leafi/devices/console.py`,
   `leafi/devices/__init__.py`, `leafi/app.py` (`build`), `leafi/runner.py`, `leafi/core/ports.py` (`Utterance`,
   `Display`), `leafi/study/brain/observe.py`, `agent/webui/__main__.py` (Host, Origin, token checks, the OCR tab),
   and the schema in `leafi/core/storage.py` (`activities`, `utterances`, `retrieval_events`, `practices`,
   `item_status_events`).
2. What will be hard to get right, and what will keep going wrong? In particular, hand-execute these on the code:
   - a console line and a panel line arriving during one prompt (D2), and a panel line typed while Leafi speaks;
   - the Ear lost with both console and panel attached, and with the panel only;
   - `/do break` pressed (a) during an offer at each autonomy band, (b) during `quiz` while it listens, (c) during
     `read_listen` mid-sentence, (d) twice with different kinds, (e) for a kind not on the menu (D7);
   - a status GET while the loop is inside a long synchronous step (an OCR read, a Brain call, `finalize`), and while
     the session is being cancelled; whether refreshing the published snapshot only inside `show()` and
     `next_utterance()` (D1) leaves it stale at any state change the owner needs to see; whether the snapshot's
     SELECTs inside `show()` can hit a busy store (ADR-0017 §7.3) or slow a line;
   - a crash that leaves `data/run/study-panel.json` behind, and two sessions started one after another (D4);
   - a panel answer in each scored activity: does D8's "`_confident` is false" reach every place that writes
     evidence (retrieval events, encounters, practices, item status, Anki eases, learner notes, the Brain's
     observation), and does it change any outcome the ADRs fix (ADR-0013 §3.4, ADR-0017 §3.1 statuses)?
   - DNS rebinding and a cross-site POST against both servers (D1, D5, D9).
3. Does any decision restate a rule owned by ADR-0013 or ADR-0017 instead of referencing it? Does any mechanism lack
   a provenance line, or rest on a research row that does not support it?
4. Anything the tests list misses, and anything that blocks landing each step as its own commit with the full suite
   green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
