"""A learner's privacy keys (ADR-0018 §5, design D10/D12): the one writer, and what egress reads.

The keys live in `learners.settings` beside the harness settings, but `leafi.study.harness.settings.save` refuses
them (they are not in its SPEC); only `write` here changes them, and it bumps the learner's `privacy.version` and,
for `cloud.text`, writes a `consents` row in the same transaction. Guests read as off whatever is stored.

`privacy.school` is the answer ADR-0018 §3 requires of every learner: `none`, or the id of a `household_terms` row
of kind `school` (siblings at one school share the row). While it is unset the learner's learner-derived text is
refused to the cloud (design D10).
"""

from __future__ import annotations

from dataclasses import dataclass

from leafi.core import learner_store
from leafi.core.storage import Store, dumps, loads, now_iso

KEYS: dict[str, object] = {"cloud.text": True, "privacy.media": "ask", "privacy.school": None}
MEDIA = ("ask", "never")
VERSION = "privacy.version"


class InvalidPrivacySetting(ValueError):
    pass


@dataclass(frozen=True)
class LearnerPrivacy:
    learner_id: int
    kind: str | None  # None: no such learner
    forgetting: bool
    cloud_text: bool
    media: str
    school: int | str | None  # a household_terms id, "none", or None (unanswered)
    version: int

    @property
    def school_answered(self) -> bool:
        return self.school is not None

    @property
    def cloud_text_allowed(self) -> bool:
        """Learner-derived text may go to the cloud: an enrolled learner, not being forgotten, `cloud.text` on,
        and the school question answered."""
        return (self.kind == "learner" and not self.forgetting and self.cloud_text and self.school_answered)


def read(store: Store, learner_id: int) -> LearnerPrivacy:
    return from_row(learner_id, store.one("SELECT kind, forgetting, settings FROM learners WHERE id=?",
                                          (learner_id,)))


def from_row(learner_id: int, row) -> LearnerPrivacy:
    """`row` holds (kind, forgetting, settings) by name or position, or is None for a missing learner."""
    if row is None:
        return LearnerPrivacy(learner_id, None, False, False, "never", None, 0)
    kind, forgetting, settings = row[0], row[1], row[2]
    values = loads(settings, {})
    guest = kind != "learner"
    return LearnerPrivacy(
        learner_id, kind, bool(forgetting),
        cloud_text=False if guest else bool(values.get("cloud.text", KEYS["cloud.text"])),
        media="never" if guest else values.get("privacy.media", KEYS["privacy.media"]),
        school=values.get("privacy.school"), version=int(values.get(VERSION, 0)))


def _validate(key: str, value: object) -> None:
    if key not in KEYS:
        raise InvalidPrivacySetting(f"{key}: not a privacy key ({', '.join(KEYS)})")
    if key == "cloud.text" and not isinstance(value, bool):
        raise InvalidPrivacySetting("cloud.text: must be on or off")
    if key == "privacy.media" and value not in MEDIA:
        raise InvalidPrivacySetting(f"privacy.media: must be one of {', '.join(MEDIA)}")
    if key == "privacy.school" and not (value == "none" or (isinstance(value, int) and not isinstance(value, bool))):
        raise InvalidPrivacySetting("privacy.school: a school term id or none")


def write(store: Store, learner_id: int, key: str, value: object, *,
          indicated_by: str = "household_setting") -> LearnerPrivacy:
    """Set one key of an enrolled learner, bump `privacy.version`, and record `cloud.text` in `consents`, in one
    transaction (design D12). The caller has shown the learner, the key and the value and had them confirmed."""
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
        if key == "cloud.text":
            learner_store.insert(store, "consents", learner_id, purpose="cloud_text",
                                 status="granted" if value else "withdrawn", valid_from=now_iso(),
                                 indicated_by=indicated_by, created_at=now_iso())
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
    with store.transaction():
        hit = store.one("SELECT id, kind FROM household_terms WHERE term = ? COLLATE NOCASE", (name,))
        if hit is None:
            term_id = store.insert("household_terms", term=name, kind="school", created_at=now_iso())
        else:
            term_id = hit["id"]
            if hit["kind"] != "school":
                store.execute("UPDATE household_terms SET kind='school' WHERE id=?", (term_id,))
        return write(store, learner_id, "privacy.school", term_id)


def school_name(store: Store, privacy: LearnerPrivacy) -> str | None:
    """What `doctor` and the console show for the owner to confirm (a voice answer is a child's ASR text)."""
    if privacy.school in (None, "none"):
        return privacy.school
    row = store.one("SELECT term FROM household_terms WHERE id=?", (privacy.school,))
    return row["term"] if row else None


def missing_school(store: Store) -> list[tuple[int, str]]:
    """Enrolled learners with no school answer: their learner-derived text stays off the cloud until one is set."""
    return [(r["id"], r["display_name"]) for r in learner_store.enrolled(store)
            if loads(r["settings"], {}).get("privacy.school") is None]
