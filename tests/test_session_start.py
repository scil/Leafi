"""ADR-0017 §2 start: lease, recovery, sweep, in order; the lease is released when recovery raises; the arm is
assigned from the adopted learner's settings; a whole default-policy session in text mode."""

from __future__ import annotations

import pytest

from leafi.core import lease as speech_lease
from leafi.core.storage import Store
from leafi.study.harness import guests, loop, rows
from leafi.study.harness import settings as hs
from tests import seed
from tests.harness_session import activities, env, run, summary

READING = ["Ada", "yes",                                   # identify: a new learner, confirmed
           None,                                           # no objection: the default chain's read_listen starts
           "The fox ran home.", "It was late and dorm.",   # one candidate (dark)
           None,                                           # practise_errors starts
           "dark",                                         # the retry passes
           "/stop"]


async def test_a_whole_text_session_runs_on_the_default_policy(settings):
    e = env(settings, READING)
    sid = await run(e)
    store = e.store
    assert activities(store, sid)[:2] == [("read_listen", "completed", False), ("practise_errors", "completed", False)]
    row = store.one("SELECT l.display_name, l.kind FROM reading_sessions s JOIN learners l ON l.id = s.learner_id "
                    "WHERE s.id=?", (sid,))
    assert (row["display_name"], row["kind"]) == ("Ada", "learner")
    assert store.one("SELECT status, withdrawn_reason FROM miscues")["withdrawn_reason"] == "practice"
    assert store.one("SELECT status FROM cycles")["status"] == "closed"
    s = summary(store, sid)
    assert s["end"] == "stop" and s["closing_line"] == "done" and s["arm"] == "default"
    assert store.one("SELECT COUNT(*) AS n FROM learners WHERE kind='guest'")["n"] == 0  # adopted: guest deleted
    acts = store.all("SELECT arm, propensity, policy_version, decided_by, autonomy FROM activities WHERE session_id=?",
                     (sid,))
    assert all(a["arm"] == "default" and a["propensity"] == 1.0 and a["policy_version"] and a["decided_by"]
               for a in acts)


async def test_recovery_and_the_sweep_run_after_the_lease_in_order(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(rows, "recover", lambda store: calls.append("recover") or [])
    monkeypatch.setattr(guests, "sweep", lambda store: calls.append("sweep") or [])
    real_acquire = speech_lease.acquire
    monkeypatch.setattr(speech_lease, "acquire", lambda *a, **k: calls.append("lease") or real_acquire(*a, **k))
    await run(env(settings, ["/stop"]))
    assert calls == ["lease", "recover", "sweep"]


async def test_the_lease_is_released_when_recovery_raises(settings, monkeypatch):
    def boom(store):
        raise RuntimeError("recovery failed")

    monkeypatch.setattr(rows, "recover", boom)
    with pytest.raises(RuntimeError):
        await run(env(settings, ["/stop"]))
    assert not speech_lease.is_held(settings.lease_path)


async def test_another_session_holding_the_lease_refuses_the_start(settings):
    import json
    import os
    import time

    settings.lease_path.parent.mkdir(parents=True, exist_ok=True)
    settings.lease_path.write_text(json.dumps({"pid": os.getppid(), "token": "someone-else",  # a live process
                                               "expires": time.time() + 60}), encoding="utf-8")
    with pytest.raises(speech_lease.LeaseHeld):
        await run(env(settings, ["/stop"]))
    assert Store(settings.db_path).one("SELECT COUNT(*) AS n FROM reading_sessions")["n"] == 0  # nothing touched


async def test_the_arm_is_assigned_from_the_adopted_learners_settings(settings):
    store = Store(settings.db_path)
    ada = seed.learner(store, "Ada")
    hs.save(store, ada, {"policy.sequencer": "brain", "policy.explore_share": 1.0})
    e = env(settings, ["/stop"], learner="Ada", brain=object())
    seen = {}
    e.on_built = lambda s, w: seen.setdefault("s", s)
    await run(e)
    assert (seen["s"].arm, seen["s"].propensity) == ("default", 1.0)  # share 1.0 from Ada's settings, not the guest's
    store2 = Store(settings.db_path)
    hs.save(store2, ada, {"policy.explore_share": 0.0})
    e2 = env(settings, ["/stop"], learner="Ada", brain=object())
    seen2 = {}
    e2.on_built = lambda s, w: seen2.setdefault("s", s)
    await run(e2)
    assert seen2["s"].arm == "brain"
    assert loop  # imported for monkeypatching in other tests
