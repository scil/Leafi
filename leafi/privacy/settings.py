"""A learner's privacy keys (ADR-0018 §5, design D10/D12): the one writer, and what egress reads.

The keys live in `learners.settings` beside the harness settings, but `leafi.study.harness.settings.save` refuses
them (they are not in its SPEC); only `write` here changes them, and it bumps the learner's `privacy.version`.
Guests read media as `never` whatever is stored.

`cloud.text` is gone (ADR-0021 E4, owner 2026-10-24): egress redacts every text by its content and never gates by
its source, so there is nothing per learner to switch. A value still stored in `learners.settings` is ignored;
`write` refuses the key. Old `consents` rows with purpose `cloud_text` stay as history; none is written.

`privacy.school` is the answer Leafi asks every learner for (ADR-0018 §3): `none`, or the id of a `household_terms`
row of kind `school` (siblings at one school share the row), so the school's name can be replaced. An unanswered
school is replaced only if the name detector finds it (owner decisions of 2026-10-24).
"""

from __future__ import annotations

from dataclasses import dataclass

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, loads, now_iso
from leafi.core.text import placeholder_reason

KEYS: dict[str, object] = {"privacy.media": "ask", "privacy.school": None}
REMOVED = {"cloud.text": "removed by ADR-0021: text leaves redacted by its content, whoever said it"}
MEDIA = ("ask", "never")
VERSION = "privacy.version"


class InvalidPrivacySetting(ValueError):
    pass


@dataclass(frozen=True)
class LearnerPrivacy:
    learner_id: int
    kind: str | None  # None: no such learner
    forgetting: bool
    media: str
    school: int | str | None  # a household_terms id, "none", or None (unanswered)
    version: int

    @property
    def school_answered(self) -> bool:
        return self.school is not None


def read(store: Store, learner_id: int) -> LearnerPrivacy:
    return from_row(learner_id, store.one("SELECT kind, forgetting, settings FROM learners WHERE id=?",
                                          (learner_id,)))


def from_row(learner_id: int, row) -> LearnerPrivacy:
    """`row` holds (kind, forgetting, settings) by name or position, or is None for a missing learner."""
    if row is None:
        return LearnerPrivacy(learner_id, None, False, "never", None, 0)
    kind, forgetting, settings = row[0], row[1], row[2]
    values = loads(settings, {})
    guest = kind != "learner"
    return LearnerPrivacy(
        learner_id, kind, bool(forgetting),
        media="never" if guest else values.get("privacy.media", KEYS["privacy.media"]),
        school=values.get("privacy.school"), version=int(values.get(VERSION, 0)))


def _validate(key: str, value: object) -> None:
    if key in REMOVED:
        raise InvalidPrivacySetting(f"{key}: {REMOVED[key]}")
    if key not in KEYS:
        raise InvalidPrivacySetting(f"{key}: not a privacy key ({', '.join(KEYS)})")
    if key == "privacy.media" and value not in MEDIA:
        raise InvalidPrivacySetting(f"privacy.media: must be one of {', '.join(MEDIA)}")
    if key == "privacy.school" and not (value == "none" or (isinstance(value, int) and not isinstance(value, bool))):
        raise InvalidPrivacySetting("privacy.school: a school term id or none")


def write(store: Store, learner_id: int, key: str, value: object) -> LearnerPrivacy:
    """Set one key of an enrolled learner and bump `privacy.version`, in one transaction (design D12). The caller
    has shown the learner, the key and the value and had them confirmed."""
    _validate(key, value)
    with store.transaction():
        row = store.one("SELECT kind, forgetting, settings FROM learners WHERE id=?", (learner_id,))
        if row is None or row["kind"] != "learner" or row["forgetting"]:
            raise InvalidPrivacySetting(f"learner #{learner_id} is not an enrolled learner")
        values = loads(row["settings"], {})
        if key == "privacy.school" and value != "none":
            hit = store.one("SELECT kind FROM household_terms WHERE id=?", (value,))
            if hit is None or hit["kind"] != "school":
                raise InvalidPrivacySetting(f"privacy.school: household term #{value} is not a school")
        values[key] = value
        values[VERSION] = int(values.get(VERSION, 0)) + 1
        store.execute("UPDATE learners SET settings=? WHERE id=?", (dumps(values), learner_id))
    return read(store, learner_id)


def set_school(store: Store, learner_id: int, school: str | None) -> LearnerPrivacy:
    """`school` is a name, or None for "no school". A name already in `household_terms` under another kind (an
    imported `REDACT_TERMS` school, say) becomes kind `school` and is linked, instead of colliding with the unique
    index (design D10)."""
    if school is None:
        return write(store, learner_id, "privacy.school", "none")
    name = school.strip()
    if not name:
        raise InvalidPrivacySetting("a school needs a name (or say no school)")
    if (why := placeholder_reason(name)) is not None:
        raise InvalidPrivacySetting(f"{name!r} is not a school's name: {why}")
    with store.transaction():
        hit = store.one("SELECT id, kind FROM household_terms WHERE term = ? COLLATE NOCASE", (name,))
        if hit is None:
            term_id = store.insert("household_terms", term=name, kind="school", created_at=now_iso())
        else:
            term_id = hit["id"]
            if hit["kind"] != "school":
                store.execute("UPDATE household_terms SET kind='school' WHERE id=?", (term_id,))
        return write(store, learner_id, "privacy.school", term_id)


TERM_KINDS = ("name", "school", "other")


def terms(store: Store) -> list[tuple[int, str, str, int | None]]:
    """(id, term, kind, former learner id) of every household term."""
    return [(r["id"], r["term"], r["kind"], r["former_learner_id"])
            for r in store.all("SELECT id, term, kind, former_learner_id FROM household_terms ORDER BY id")]


def add_term(store: Store, term: str, kind: str = "name") -> int:
    """A protected name, school or other term (ADR-0018 §3 lists). An existing term (any case) changes kind."""
    name = term.strip()
    if not name:
        raise InvalidPrivacySetting("a term needs some text")
    if (why := placeholder_reason(name)) is not None:
        raise InvalidPrivacySetting(f"{name!r} is not a term to protect: {why}")
    if kind not in TERM_KINDS:
        raise InvalidPrivacySetting(f"kind must be one of {', '.join(TERM_KINDS)}")
    with store.transaction():
        hit = store.one("SELECT id, kind FROM household_terms WHERE term = ? COLLATE NOCASE", (name,))
        if hit is not None:
            if hit["kind"] != kind:
                store.execute("UPDATE household_terms SET kind=? WHERE id=?", (kind, hit["id"]))
            return hit["id"]
        return store.insert("household_terms", term=name, kind=kind, created_at=now_iso())


def remove_term(store: Store, term: str) -> list[str]:
    """Remove a term; returns what else changed. A learner whose school it was has no school answer again (the
    school can no longer be replaced by the lists); a surrogate goes with the last term of its entity."""
    effects: list[str] = []
    with store.transaction():
        hit = store.one("SELECT id, kind, former_learner_id FROM household_terms WHERE term = ? COLLATE NOCASE",
                        (term.strip(),))
        if hit is None:
            raise InvalidPrivacySetting(f"no household term {term!r}")
        for r in learner_store.enrolled(store):
            values = loads(r["settings"], {})
            if values.get("privacy.school") == hit["id"]:
                values.pop("privacy.school")
                values[VERSION] = int(values.get(VERSION, 0)) + 1
                store.execute("UPDATE learners SET settings=? WHERE id=?", (dumps(values), r["id"]))
                effects.append(f"learner #{r['id']} {r['display_name']} has no school answer now")
        store.execute("DELETE FROM household_terms WHERE id=?", (hit["id"],))
        store.execute("DELETE FROM pseudonyms WHERE entity=?", (f"term:{hit['id']}",))
        former = hit["former_learner_id"]
        if former is not None and not store.one("SELECT 1 FROM household_terms WHERE former_learner_id=?",
                                                (former,)):
            store.execute("DELETE FROM pseudonyms WHERE entity=?", (f"former:{former}",))
    return effects


def school_name(store: Store, privacy: LearnerPrivacy) -> str | None:
    """What `doctor` and the console show for the owner to confirm (a voice answer is a child's ASR text)."""
    if privacy.school in (None, "none"):
        return privacy.school
    row = store.one("SELECT term FROM household_terms WHERE id=?", (privacy.school,))
    return row["term"] if row else None


def missing_school(store: Store) -> list[tuple[int, str]]:
    """Enrolled learners with no school answer: their school cannot be replaced by the lists (only the name
    detector may catch it), so `doctor` and the `household-terms` check ask for it."""
    return [(r["id"], r["display_name"]) for r in learner_store.enrolled(store)
            if loads(r["settings"], {}).get("privacy.school") is None]
