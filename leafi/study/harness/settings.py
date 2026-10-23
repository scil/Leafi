"""Per-learner study settings (ADR-0017 §2.1, §3.3, §6.1, §6.3; ADR-0018 §1): every number is a setting with a
range checked when it is saved (owner decision 2026-10-22); an invalid value is refused with the reason.

Stored as dotted keys in `learners.settings` (JSON); `learners.settings_version` changes with every save, which
`checkpoint` notices (ADR-0017 §1).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from leafi.core.storage import Store, dumps, loads
from leafi.study.harness.ledger import Limits

CONTENT_KINDS = ("review_anki", "read_listen", "read_aloud", "practise_errors", "teach_items", "recall_items",
                 "quiz", "learner_questions", "add_cards", "break", "end")
BRAIN_ONLY = frozenset({"teach_items", "quiz", "learner_questions"})  # no `code` content owner (§1)

# key: (default, check) — check is (lo, hi) for numbers or a tuple of allowed strings
SPEC: dict[str, tuple[object, object]] = {
    "autonomy": (5, (0, 10)),
    "bands.ask": (2, (1, 11)),
    "bands.argue": (4, (1, 11)),
    "bands.announce": (8, (1, 11)),
    "negotiation.max_offers": (3, (1, 5)),
    "negotiation.choices": (3, (2, 5)),
    "negotiation.ask_s": (8, (3, 30)),
    "negotiation.wait_s": (30, (10, 120)),
    "negotiation.silence_reasks": (1, (0, 3)),
    "practice.max_errors": (5, (0, 20)),
    "practice.max_new_cycle": (3, (0, 10)),
    "practice.max_new_session": (8, (0, 30)),
    "quiz.max_questions": (4, (0, 10)),
    "cards.max": (10, (0, 50)),
    "session.max_min": (None, (5, 30)),  # None = by age band (15 for ages 6-7, else 20); ceiling 30
    "session.max_min_unknown_age": (15, (5, 30)),
    "session.max_min_guest": (15, (5, 30)),
    "session.end_mode": ("finish_activity", ("finish_activity", "hard")),
    "session.grace_min": (3, (0, 10)),
    "limits.activity_max_min": (8, (1, 30)),
    "limits.activities_per_cycle": (6, (1, 20)),
    "limits.brain_calls_per_session": (40, (0, 200)),
    "policy.sequencer": ("brain", ("brain", "default")),
    "policy.explore_share": (0.1, (0.0, 1.0)),
    "reading.interrupt": ("stuck_only", ("never", "stuck_only", "sentence_end")),
    "reading.encourage": ("specific", ("none", "specific", "frequent")),
    "reading.silence_backchannel_s": (3, (1, 30)),
    "reading.silence_prompt_s": (3, (1, 30)),
}
for _k in CONTENT_KINDS:
    SPEC[f"policy.content.{_k}"] = ("brain" if _k in BRAIN_ONLY else "code",
                                    ("brain",) if _k in BRAIN_ONLY else ("code",) if _k == "end" else ("code", "brain"))
# `end` is always constructible: its content owner is fixed to `code` (a static closing line, §3.1)


class InvalidSetting(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def validate(values: dict) -> dict[str, str]:
    """Reasons per key; empty when every value is in range and the bands are ordered."""
    errors: dict[str, str] = {}
    for key, value in values.items():
        if key == "policy.default_order":
            from leafi.study.harness import policy  # the order has its own validation

            reason = policy.invalid_order(value)
            if reason:
                errors[key] = reason
            continue
        if key not in SPEC:
            errors[key] = "unknown setting"
            continue
        default, check = SPEC[key]
        if value is None and default is None:
            continue
        if isinstance(check[0], str):
            if value not in check:
                errors[key] = f"must be one of {', '.join(check)}"
        elif isinstance(value, bool) or not isinstance(value, int | float):
            errors[key] = "must be a number"
        elif not check[0] <= value <= check[1]:
            errors[key] = f"must be between {check[0]} and {check[1]}"
    merged = {k: d for k, (d, _) in SPEC.items()} | values
    a, g, n = merged["bands.ask"], merged["bands.argue"], merged["bands.announce"]
    if not errors.keys() & {"bands.ask", "bands.argue", "bands.announce"} and not 1 <= a <= g <= n <= 11:
        errors["bands"] = "needs 1 <= bands.ask <= bands.argue <= bands.announce <= 11"
    return errors


@dataclass(frozen=True)
class LearnerSettings:
    values: dict
    version: int = 1
    kind: str = "learner"
    birth_year: int | None = None

    def __getitem__(self, key: str):
        if key in self.values:
            return self.values[key]
        if key == "policy.default_order":
            from leafi.study.harness import policy

            return policy.BUILT_IN
        return SPEC[key][0]

    def session_max_min(self, today: dt.date | None = None) -> int:
        """§6.3: guests and unknown ages have their own settings; otherwise by age band, ceiling 30."""
        if self.kind in ("guest", "anonymous"):
            return int(self["session.max_min_guest"])
        if self.values.get("session.max_min") is not None:
            return min(30, int(self.values["session.max_min"]))
        if self.birth_year is None:
            return int(self["session.max_min_unknown_age"])
        age = (today or dt.date.today()).year - self.birth_year
        return 15 if age <= 7 else 20

    def limits(self) -> Limits:
        return Limits(max_errors=self["practice.max_errors"], max_new_cycle=self["practice.max_new_cycle"],
                      max_new_session=self["practice.max_new_session"], quiz_max=self["quiz.max_questions"],
                      cards_max=self["cards.max"], activities_per_cycle=self["limits.activities_per_cycle"],
                      brain_calls=float(self["limits.brain_calls_per_session"]))


def load(store: Store, learner_id: int) -> LearnerSettings:
    row = store.one("SELECT kind, birth_year, settings, settings_version FROM learners WHERE id=?", (learner_id,))
    if row is None:
        return LearnerSettings({})
    values = {k: v for k, v in loads(row["settings"], {}).items() if k in SPEC or k == "policy.default_order"}
    return LearnerSettings(values, row["settings_version"], row["kind"], row["birth_year"])


def save(store: Store, learner_id: int, changes: dict) -> LearnerSettings:
    """Validate, then merge and bump `settings_version` in one statement; InvalidSetting names every reason."""
    errors = validate(changes)
    if errors:
        raise InvalidSetting(errors)
    with store.transaction():
        row = store.one("SELECT settings FROM learners WHERE id=?", (learner_id,))
        merged = loads(row["settings"], {}) | changes
        store.execute("UPDATE learners SET settings=?, settings_version=settings_version+1 WHERE id=?",
                      (dumps(merged), learner_id))
    return load(store, learner_id)


def version(store: Store, learner_id: int) -> int:
    row = store.one("SELECT settings_version FROM learners WHERE id=?", (learner_id,))
    return row["settings_version"] if row else 0
