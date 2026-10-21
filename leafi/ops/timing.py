"""Supervision timing settings (ADR-0016): the one parser and validator.

Every supervision number is a setting; this module turns them into a `Timing` and checks the invariants between
them. A violated invariant makes every setting it involves fall back to its default (the defaults satisfy all
invariants together), so the supervisor always runs with a consistent set and never exits over timing; the
`supervision-timing` configuration check reports the violation. Timeouts stay constants here: they give the
worst-case duration of one poll, which the invariants need.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from pathlib import Path

# Per-service worst-case seconds one observation can take (the probe timeouts in supervisor.py): the camera reads
# /api/streams (3), asks Frigate whether it wants the stream (3) and fetches one frame (15).
PROBE_WORST_S = {"camera": 21.0, "docker": 15.0, "frigate": 3.0, "mosquitto": 3.0, "gatus": 3.0, "ollama": 3.0,
                 "habit-agent": 0.0}
# Measured start-up times: a grace shorter than this judges a service BAD before it is up.
MIN_GRACE_S = {"docker": 120.0, "frigate": 60.0, "camera": 60.0}
DEFAULT_GRACE = {"camera": 90.0, "habit-agent": 90.0, "docker": 180.0, "frigate": 120.0, "mosquitto": 60.0,
                 "gatus": 60.0, "ollama": 60.0}


@dataclass(frozen=True)
class Timing:
    poll_s: float = 60.0
    bad_streak: int = 2
    max_recoveries: int = 3
    healthy_s: float = 600.0
    grace: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_GRACE))
    resume_gap_s: float = 180.0
    resume_grace_s: float = 120.0
    checks_every_s: float = 900.0
    task_repeat_min: int = 5
    keep_backoff_s: tuple[float, ...] = (5.0, 30.0, 120.0, 300.0)
    keep_crash_exits: int = 3
    keep_crash_window_min: float = 30.0


DEFAULTS = Timing()


HEARTBEAT_LIMIT_S = 5.0  # checks.heartbeat
PUSH_LIMIT_S = 3.0       # checks.push, once per service plus leafi/supervisor


def worst_poll_s(services) -> float:
    """Worst-case time one poll iteration takes: every probe, then the heartbeat and the dashboard pushes."""
    services = list(services)
    return (sum(PROBE_WORST_S.get(s, 3.0) for s in services) + HEARTBEAT_LIMIT_S
            + PUSH_LIMIT_S * (len(services) + 1))


def violations(t: Timing, services) -> list[tuple[str, tuple[str, ...]]]:
    """Every broken invariant as (problem id, the Timing fields it involves)."""
    w = worst_poll_s(services)
    out: list[tuple[str, tuple[str, ...]]] = []

    def need(ok: bool, problem: str, *involved: str) -> None:
        if not ok:
            out.append((problem, involved))

    need(t.resume_gap_s > t.poll_s + w, "resume-gap", "resume_gap_s", "poll_s")
    need(t.resume_grace_s >= t.poll_s, "resume-grace", "resume_grace_s", "poll_s")
    need(all(g > 0 for g in t.grace.values()) and all(t.grace.get(s, 0) >= m for s, m in MIN_GRACE_S.items()),
         "grace", "grace")
    need(t.healthy_s >= 3 * t.poll_s and t.healthy_s > max(t.grace.values()), "healthy", "healthy_s", "poll_s", "grace")
    need(2 <= t.bad_streak <= 10, "bad-streak", "bad_streak")
    need(1 <= t.max_recoveries <= 10, "max-recoveries", "max_recoveries")
    need(t.checks_every_s >= 60, "checks-every", "checks_every_s")
    need(t.task_repeat_min >= 1, "task-repeat", "task_repeat_min")
    backoff = t.keep_backoff_s
    need(bool(backoff) and all(b > 0 for b in backoff) and all(a <= b for a, b in zip(backoff, backoff[1:], strict=False)),
         "keep-backoff", "keep_backoff_s")
    need(t.keep_crash_exits >= 2, "keep-exits", "keep_crash_exits")
    if t.keep_crash_exits >= 2 and backoff:
        # A crash loop ends up waiting the last (longest) delay between exits, so that many exits must still fit:
        # KEEP_CRASH_EXITS exits are separated by KEEP_CRASH_EXITS - 1 waits.
        need(t.keep_crash_window_min * 60 > (t.keep_crash_exits - 1) * max(backoff), "keep-window",
             "keep_backoff_s", "keep_crash_window_min", "keep_crash_exits")
    return out


def parse_grace(text: str) -> dict[str, float]:
    """`SUPERVISOR_GRACE` -> the per-service overrides; raises ValueError. Pure: also the settings page's validator."""
    out: dict[str, float] = {}
    for item in filter(None, (p.strip() for p in text.split(","))):
        name, _, value = item.partition("=")
        out[name.strip()] = float(value)
    return out


def parse_backoff(text: str) -> tuple[float, ...]:
    """`KEEP_BACKOFF_S` -> the delays; raises ValueError. Pure: also the settings page's validator."""
    return tuple(float(x) for x in text.split(",") if x.strip())


def _parse(settings) -> tuple[Timing, list[str]]:
    """Read the settings; a value that does not parse is a problem and stays at its default."""
    problems: list[str] = []
    grace = dict(DEFAULT_GRACE)
    try:
        grace.update(parse_grace(settings.supervisor_grace))
    except ValueError:
        problems.append("grace")
        grace = dict(DEFAULT_GRACE)
    try:
        backoff = parse_backoff(settings.keep_backoff_s)
    except ValueError:
        problems.append("keep-backoff")
        backoff = DEFAULTS.keep_backoff_s
    return Timing(poll_s=float(settings.supervisor_poll_s), bad_streak=int(settings.supervisor_bad_streak),
                  max_recoveries=int(settings.supervisor_max_recoveries), healthy_s=float(settings.supervisor_healthy_s),
                  grace=grace, resume_gap_s=float(settings.supervisor_resume_gap_s),
                  resume_grace_s=float(settings.supervisor_resume_grace_s),
                  checks_every_s=float(settings.checks_every_s), task_repeat_min=int(settings.task_repeat_min),
                  keep_backoff_s=backoff, keep_crash_exits=int(settings.keep_crash_exits),
                  keep_crash_window_min=float(settings.keep_crash_window_min)), problems


def resolve(settings) -> tuple[Timing, list[str]]:
    """The timing the supervisor runs with, and the problems found. Fallback converges: each round resets at
    least one field to its default, and the all-default set has no violation."""
    t, problems = _parse(settings)
    services = [s.strip() for s in settings.supervise.split(",") if s.strip()]
    for _ in range(len(fields(Timing)) + 1):
        broken = violations(t, services)
        if not broken:
            break
        reset = {f for _, involved in broken for f in involved}
        problems += [p for p, _ in broken if p not in problems]
        t = replace(t, **{f: getattr(DEFAULTS, f) for f in reset})
    return t, problems


def gatus_heartbeat_s(path: Path) -> float | None:
    """The `leafi/supervisor` heartbeat interval in the dashboard config (`300s`, `5m`, `1h`)."""
    import yaml

    try:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    for e in cfg.get("external-endpoints") or []:
        if e.get("name") == "supervisor" and e.get("group") == "leafi":
            raw = str((e.get("heartbeat") or {}).get("interval", ""))
            units = {"s": 1, "m": 60, "h": 3600}
            if raw[:-1].isdigit() and raw[-1:] in units:
                return float(raw[:-1]) * units[raw[-1]]
    return None


def heartbeat_ok(interval_s: float | None, t: Timing, services) -> bool:
    return interval_s is not None and interval_s > t.poll_s + worst_poll_s(services)


@dataclass(frozen=True)
class Derived:
    service: str
    first_recovery_s: float
    give_up_s: float


def derived(t: Timing, services) -> list[Derived]:
    """Upper bounds, from the moment a service breaks, for a service that stays broken; each recovery's own run
    time comes on top. The outage is seen within one poll and BAD_STREAK polls later the first recovery starts;
    after each recovery the grace swallows whole polls (rounded up), then BAD_STREAK - 1 more polls trigger the
    next recovery, and after MAX_RECOVERIES of them the next streak gives up."""
    first = t.bad_streak * t.poll_s
    out = []
    for s in services:
        grace = t.grace.get(s, 60.0)
        cycle = -(-grace // t.poll_s) * t.poll_s + (t.bad_streak - 1) * t.poll_s
        out.append(Derived(s, first, first + t.max_recoveries * cycle))
    return out


def as_env(t: Timing) -> list[str]:
    """Validated values for the PowerShell scripts (keep.ps1, install-tasks.ps1)."""
    return [f"KEEP_BACKOFF_S={','.join(f'{b:g}' for b in t.keep_backoff_s)}", f"KEEP_CRASH_EXITS={t.keep_crash_exits}",
            f"KEEP_CRASH_WINDOW_MIN={t.keep_crash_window_min:g}", f"TASK_REPEAT_MIN={t.task_repeat_min}"]
