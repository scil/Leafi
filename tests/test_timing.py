"""ADR-0016 timing settings: one parser, the invariants, fallback to defaults, derived timings, script values."""

from __future__ import annotations

import random

import pytest

from leafi.core.config import Settings
from leafi.ops import timing

ALL = ["docker", "camera", "habit-agent", "frigate", "mosquitto", "gatus", "ollama"]


def _settings(**kw) -> Settings:
    s = Settings(_env_file=None)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_the_defaults_satisfy_every_invariant_even_with_every_service_enabled():
    t, problems = timing.resolve(_settings(supervise=",".join(ALL)))
    assert problems == []
    assert t == timing.resolve(_settings())[0]


def test_grace_is_parsed_per_service():
    t, problems = timing.resolve(_settings(supervisor_grace="camera=100,docker=200,frigate=90,mosquitto=60,"
                                                            "gatus=60,habit-agent=90,ollama=60"))
    assert problems == [] and t.grace["camera"] == 100 and t.grace["docker"] == 200


@pytest.mark.parametrize("changes, problem, fell_back", [
    ({"supervisor_resume_gap_s": 90}, "resume-gap", ["resume_gap_s", "poll_s"]),
    ({"supervisor_resume_grace_s": 30}, "resume-grace", ["resume_grace_s"]),
    ({"supervisor_healthy_s": 120}, "healthy", ["healthy_s"]),
    ({"supervisor_grace": "docker=30"}, "grace", ["grace"]),
    ({"keep_backoff_s": "5,30,900", "keep_crash_window_min": 20}, "keep-window",  # saturated: 2 × 900 s > 1200 s
     ["keep_backoff_s", "keep_crash_window_min", "keep_crash_exits"]),
    ({"supervisor_grace": "camera=ninety"}, "grace", ["grace"]),
    ({"supervisor_bad_streak": 1}, "bad-streak", ["bad_streak"]),
    ({"supervisor_max_recoveries": 0}, "max-recoveries", ["max_recoveries"]),
    ({"checks_every_s": 10}, "checks-every", ["checks_every_s"]),
    ({"task_repeat_min": 0}, "task-repeat", ["task_repeat_min"]),
    ({"keep_backoff_s": "60,30,10"}, "keep-backoff", ["keep_backoff_s"]),
    ({"keep_backoff_s": "300,600,1200", "keep_crash_window_min": 10}, "keep-window",  # 2 waits = 900 s > 600 s
     ["keep_backoff_s", "keep_crash_window_min"]),
    ({"keep_crash_exits": 1}, "keep-exits", ["keep_crash_exits"]),
])
def test_a_violated_invariant_falls_back_to_the_defaults_of_every_setting_involved(changes, problem, fell_back):
    t, problems = timing.resolve(_settings(**changes))
    assert problem in problems
    for field in fell_back:
        assert getattr(t, field) == getattr(timing.DEFAULTS, field), field
    assert timing.violations(t, ALL) == []  # what the supervisor runs with is always consistent


def test_a_grace_shorter_than_a_poll_is_fine_when_it_covers_start_up():
    t, problems = timing.resolve(_settings(supervisor_poll_s=120, supervisor_healthy_s=900,
                                           supervisor_resume_gap_s=300, supervisor_resume_grace_s=120))
    assert problems == [] and t.poll_s == 120  # camera 90 s < 120 s poll: the next poll comes after start-up


def test_fallback_that_creates_a_new_violation_is_revalidated_until_stable():
    """Codex: resetting the grace map (docker 180) can break a short healthy window; resetting poll can break
    3 × POLL. The loop repeats until the set is consistent and keeps every original problem."""
    t, problems = timing.resolve(_settings(supervisor_poll_s=10, supervisor_healthy_s=150,
                                           supervisor_grace="camera=30,docker=120"))
    assert "grace" in problems
    assert timing.violations(t, ALL) == []


def test_a_large_poll_interval_pulls_its_dependants_back_to_a_consistent_set():
    t, problems = timing.resolve(_settings(supervisor_poll_s=300))
    assert problems  # 300 s polls break the default resume gap, grace and healthy window
    assert timing.violations(t, ALL) == []


def test_random_settings_always_resolve_to_a_consistent_set():
    rnd = random.Random(16)
    for _ in range(300):
        s = _settings(
            supervisor_poll_s=rnd.choice([5, 30, 60, 120, 300, 900]),
            supervisor_bad_streak=rnd.choice([0, 1, 2, 3, 20]),
            supervisor_max_recoveries=rnd.choice([0, 1, 3, 50]),
            supervisor_healthy_s=rnd.choice([30, 300, 600, 3600]),
            supervisor_resume_gap_s=rnd.choice([30, 180, 600]),
            supervisor_resume_grace_s=rnd.choice([10, 120, 600]),
            supervisor_grace=rnd.choice(["", "docker=30", "camera=90,docker=600", "x"]),
            keep_backoff_s=rnd.choice(["5,30,120,300", "300,5", "1", "a,b"]),
            keep_crash_exits=rnd.choice([1, 3, 6]),
            keep_crash_window_min=rnd.choice([1, 30, 120]),
            supervise=",".join(rnd.sample(ALL, rnd.randint(1, len(ALL)))),
        )
        t, _ = timing.resolve(s)
        assert timing.violations(t, s.supervise.split(",")) == [], s


def test_gatus_heartbeat_interval_is_read_from_the_dashboard_config(tmp_path):
    from tests.test_architecture import ROOT

    assert timing.gatus_heartbeat_s(ROOT / "config" / "gatus" / "config.yaml") == 300
    f = tmp_path / "c.yaml"
    f.write_text("external-endpoints:\n  - {name: supervisor, group: leafi, heartbeat: {interval: 90s}}\n",
                 encoding="utf-8")
    assert timing.gatus_heartbeat_s(f) == 90
    assert timing.heartbeat_ok(90, timing.DEFAULTS, ALL) is False  # 90 s < 60 s poll + worst poll (+ reporting)
    assert timing.heartbeat_ok(300, timing.DEFAULTS, ALL) is True


def test_derived_timings_follow_the_policy():
    rows = {r.service: r for r in timing.derived(timing.DEFAULTS, ["camera", "docker"])}
    assert rows["camera"].first_recovery_s == 120  # seen within one poll, then the second BAD poll
    # camera: a 90 s grace swallows one poll, the next counts, one more triggers: a 180 s cycle; three cycles
    assert rows["camera"].give_up_s == 120 + 3 * 180
    assert rows["docker"].give_up_s == 120 + 3 * (180 + 60)  # 180 s grace = 3 polls, the 3rd already counts


def test_derived_camera_timing_matches_the_policy_trace(tmp_path):
    """Cross-check with the ServicePolicy itself: restarts at 1, 4, 7 min and give-up at 10 min after the first
    BAD poll, which is at most one poll after the break."""
    import functools

    from leafi.core.storage import Store
    from leafi.ops.supervisor import BAD, ServicePolicy

    p = functools.partial(ServicePolicy, service="camera", grace_s=90.0)(Store(tmp_path / "x.db"))
    p.started(-10_000)
    mono, events = 0.0, []
    for i in range(15):
        if p.step(BAD, mono, 1e6 + mono):
            events.append(i)
            p.started(mono)
        if p._state()["gave_up"] and "gave_up" not in events:
            events.append("gave_up")
            events.append(i)
        mono += 60
    assert events == [1, 4, 7, "gave_up", 10]
    give_up_after_first_bad = 10 * 60
    assert give_up_after_first_bad + 60 == timing.derived(timing.DEFAULTS, ["camera"])[0].give_up_s


def test_scripts_get_the_validated_values_as_key_value_lines():
    lines = timing.as_env(timing.resolve(_settings(keep_backoff_s="10,60,600", task_repeat_min=7))[0])
    assert "KEEP_BACKOFF_S=10,60,600" in lines and "TASK_REPEAT_MIN=7" in lines
    assert "KEEP_CRASH_EXITS=3" in lines and "KEEP_CRASH_WINDOW_MIN=30" in lines
