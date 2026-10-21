"""The `.env` settings catalog and the save coordinator (docs/plans/active/2026-10-21-env-settings-page.md §3-§5).

Outer ring, beside `cli.py`: it reads both Settings classes, the service registries, `.env.example`, the docs table
and every `${VAR}` reference, and drives `leafi.core.envfile.update_env` with a validating `transform`. Values are
never logged; secret values never leave this module except into the file.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from leafi.core import envfile
from leafi.core.config import Settings as LeafiSettings
from leafi.core.config import env_overrides
from leafi.core.envfile import ABSENT, Committed, Conflict, EnvFile, Op, RecoveryRequired, Unstorable

log = logging.getLogger("leafi.envedit")

ROOT = Path(__file__).resolve().parents[1]

SECRET_KEYS = {"TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "CAM_PASSWORD", "TAPO_CLOUD_PASSWORD", "GATUS_TOKEN",
               "BARK_URL", "HEARTBEAT_URL"}
SECRET_NAME = re.compile(r"(?i)(TOKEN|PASSW|SECRET|KEY|CREDENTIAL|PRIVATE)")

# ADR-0011: changing these changes what may leave the house; a save needs a confirmation bound to the new value
PRIVACY_KEYS = {"NOTIFY_WITH_SNAPSHOT", "BOOK_LOOKUP", "AUDIO_KEEP_CLIPS", "EVAL_TRANSCRIPTS", "REDACT_TERMS",
                "BRAIN_BACKEND", "STUDY_BRAIN_MODEL", "TTS_BACKEND_EN", "TTS_BACKEND_ZH"}

# Enum-like keys without a service registry (the registries cover *_BACKEND)
ENUMS = {"ASR_HOTWORDS": ("off", "lexicon"), "OCR_SNAP": ("off", "advisory", "auto"),
         "BOOK_LOOKUP": ("off", "openlibrary"), "OCR_VERSION": ("PP-OCRv6", "PP-OCRv5"),
         "VERIFY_MODE": ("presence", "vision"), "SPEAKER_BACKEND": ("go2rtc", "local")}

READER_LEAFI, READER_HABIT = "leafi", "habit agent"
ACTIVATION = {
    READER_LEAFI: "restart the supervisor (Leafi console) and any running study session",
    READER_HABIT: "restart the habit agent",
    "devices.yml": "restart the supervisor (Leafi console) and any running study session",
    "frigate": r"run scripts\win\apply-env.bat (recreates the Frigate container)",
    "compose:frigate": r"run scripts\win\apply-env.bat (recreates the Frigate container)",
    "gatus": "docker compose up -d gatus",
    "logon task": r"rerun scripts\win\install-tasks.ps1",
    "keep.ps1": "restart the supervisor task (keep.ps1 reads them at start)",
}


def activation(reader: str) -> str | None:
    if reader in ACTIVATION:
        return ACTIVATION[reader]
    if reader.startswith("compose:"):
        return f"docker compose up -d {reader.split(':', 1)[1]}"
    return None


def _registries() -> dict[str, Any]:
    from leafi.services.asr import REGISTRY as asr
    from leafi.services.brain import REGISTRY as brain
    from leafi.services.ocr import REGISTRY as ocr
    from leafi.services.pronunciation import REGISTRY as pron
    from leafi.services.tts import REGISTRY as tts

    return {"ASR_BACKEND": asr, "OCR_BACKEND": ocr, "PRON_BACKEND": pron, "BRAIN_BACKEND": brain,
            "TTS_BACKEND_EN": tts, "TTS_BACKEND_ZH": tts}


def _gates() -> dict[str, Any]:
    """ADR-0011 / ADR-0003 release gates: predicates on the typed value; the page never sets a gated value."""
    regs = _registries()
    return {
        "PRON_AUTO_JUDGE": lambda v: v is True,
        "ASR_HOTWORDS": lambda v: v == "lexicon",
        "OCR_SNAP": lambda v: v == "auto",
        "ASR_BACKEND": lambda v: v in regs["ASR_BACKEND"].deferred,
        "OCR_BACKEND": lambda v: v in regs["OCR_BACKEND"].deferred,
        "BRAIN_BACKEND": lambda v: v == "ollama",
        "OCR_SECOND_OPINION": lambda v: v != "",
        "BRAIN_LOCAL_MODEL": lambda v: v != "",
    }


def _habit_settings_class():
    from agent.config import Settings

    return Settings


# ---------------------------------------------------------------- catalog


@dataclass
class Entry:
    key: str
    section: str | None = None
    order: int = 10_000
    help: str = ""
    readers: list[str] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)
    types: dict[str, Any] = field(default_factory=dict)  # reader -> annotation
    unknown: bool = False

    @property
    def secret(self) -> bool:
        return self.key in SECRET_KEYS or bool(SECRET_NAME.search(self.key))

    @property
    def privacy(self) -> bool:
        return self.key in PRIVACY_KEYS

    def add_reader(self, reader: str) -> None:
        if reader not in self.readers:
            self.readers.append(reader)


def _show(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Path):
        return v.as_posix()
    return str(v)


@dataclass
class Catalog:
    entries: dict[str, Entry]
    sections: list[str]
    anchors: dict[str, str]


@lru_cache(maxsize=1)
def _static_catalog(root: Path) -> Catalog:
    entries: dict[str, Entry] = {}

    def entry(key: str) -> Entry:
        return entries.setdefault(key, Entry(key))

    for reader, cls in ((READER_LEAFI, LeafiSettings), (READER_HABIT, _habit_settings_class())):
        for name, f in cls.model_fields.items():
            e = entry(name.upper())
            e.add_reader(reader)
            e.types[reader] = f.annotation
            e.defaults[reader] = _show(f.default)

    sections: list[str] = []
    anchors: dict[str, str] = {}
    section = None
    example = root / ".env.example"
    if example.exists():
        for i, ln in enumerate(example.read_text(encoding="utf-8").splitlines()):
            if ln.startswith("# ====="):
                section = ln
                sections.append(ln)
                continue
            m = re.match(r"^#?\s*([A-Z][A-Z0-9_]*)=([^#]*?)(?:\s+#\s*(.*))?$", ln)
            if m:
                e = entry(m.group(1))
                if e.section is None:
                    e.section, e.order = section, i
                    if section:
                        anchors[e.key] = section
                if m.group(3) and not e.help:
                    e.help = m.group(3).strip()

    doc = root / "docs" / "architecture" / "config.md"
    if doc.exists():
        for ln in doc.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\| ((?:`[A-Z][A-Z0-9_]*`(?: / )?)+) \| (.*?) \| (.*) \|$", ln)
            if m:
                for key in re.findall(r"`([A-Z][A-Z0-9_]*)`", m.group(1)):
                    e = entry(key)
                    if not e.help:
                        e.help = m.group(3).strip()

    ref = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?:(:?-)([^}]*))?\}")
    compose = root / "docker-compose.yml"
    if compose.exists():
        import yaml

        services = (yaml.safe_load(compose.read_text(encoding="utf-8")) or {}).get("services", {})
        for svc, spec in services.items():
            for m in ref.finditer(yaml.safe_dump(spec)):
                e = entry(m.group(1))
                e.add_reader(f"compose:{svc}")
                if m.group(2):
                    e.defaults[f"compose:{svc}"] = m.group(3) + ("  (also when empty)" if m.group(2) == ":-" else "")
    for reader, files in (("devices.yml", [root / "config" / "devices.yml"]),
                          ("gatus", [root / "config" / "gatus" / "config.yaml"]),
                          ("frigate", sorted((root / "config" / "frigate").glob("*.yml")))):
        for f in files:
            if f.exists():
                text = "\n".join(ln for ln in f.read_text(encoding="utf-8").splitlines()
                                 if not ln.lstrip().startswith("#"))  # a ${VAR} in a comment reads nothing
                for m in ref.finditer(text):
                    entry(m.group(1)).add_reader(reader)

    timing_ps1 = root / "scripts" / "win" / "timing.ps1"
    if timing_ps1.exists():
        for key, default in re.findall(r"\b((?:KEEP|TASK)_[A-Z_]+) = \"([^\"]*)\"", timing_ps1.read_text(encoding="utf-8")):
            e = entry(key)
            reader = "logon task" if key == "TASK_REPEAT_MIN" else "keep.ps1"
            e.add_reader(reader)
            e.defaults[reader] = default

    return Catalog(entries, sections, anchors)


def catalog(env_keys: set[str] = frozenset(), root: Path = ROOT) -> Catalog:
    """The static catalog plus an Unknown entry for every `.env` key no reader knows (masked, unset only)."""
    static = _static_catalog(root)
    entries = dict(static.entries)
    for key in env_keys - set(entries):
        entries[key] = Entry(key, help="no reader found: probably a stale name", unknown=True)
    for e in entries.values():
        if not e.readers and e.section and not e.help:
            e.help = "documented in .env.example; no program in this repository reads it"
    return Catalog(entries, static.sections, static.anchors)


def is_unknown(e: Entry) -> bool:
    """In `.env` but in no source at all; a key documented in `.env.example` that nothing reads is not unknown."""
    return e.unknown


def is_secret(e: Entry) -> bool:
    return e.secret or is_unknown(e)


def allowed(e: Entry) -> list[str] | None:
    gates = _gates()
    regs = _registries()
    if e.key in regs:
        options = sorted(regs[e.key].backends)
    elif e.key in ENUMS:
        options = list(ENUMS[e.key])
    else:
        return None
    gate = gates.get(e.key)
    return [o for o in options if not (gate and gate(o))]


def typed(e: Entry, text: str) -> Any:
    """The value each reader would hold; raises ValueError with a rule (never the value)."""
    out = None
    for reader in (READER_LEAFI, READER_HABIT):
        if reader in e.types:
            try:
                v = TypeAdapter(e.types[reader]).validate_strings(text)
            except ValidationError as err:
                raise ValueError(err.errors()[0]["msg"]) from None
            out = v if out is None else out
    return text if out is None else out


def gated(e: Entry, value: Any) -> bool:
    gate = _gates().get(e.key)
    return bool(gate and gate(value))


def _kind(e: Entry) -> str:
    if is_secret(e):
        return "secret"
    if allowed(e) is not None:
        return "enum"
    ann = e.types.get(READER_LEAFI) or e.types.get(READER_HABIT)
    return {bool: "bool", int: "int", float: "float"}.get(ann, "text")


# ---------------------------------------------------------------- the GET body


def _group_name(e: Entry) -> str:
    if e.section:
        return e.section.strip("# =").strip()
    if is_unknown(e):
        return "Unknown"
    if READER_LEAFI in e.readers:
        return "Study and ops (leafi)"
    if READER_HABIT in e.readers:
        return "Habit agent"
    return "Compose only"


def view(path: Path = Path(".env"), root: Path = ROOT) -> dict:
    raw, digest = envfile.read_state(Path(path))
    f = EnvFile.parse(raw)
    problems = f.problems()
    values = {} if problems else f.values()
    cat = catalog(set(values), root)
    groups: dict[str, list[dict]] = {}
    order = {s.strip("# =").strip(): i for i, s in enumerate(cat.sections)}
    for e in sorted(cat.entries.values(), key=lambda x: (x.order, x.key)):
        state = "default" if e.key not in values else ("empty" if values[e.key] == "" else "set")
        item = {"key": e.key, "state": state, "help": e.help, "readers": e.readers, "defaults": e.defaults,
                "activation": sorted({a for r in e.readers if (a := activation(r))}), "secret": is_secret(e),
                "privacy": e.privacy, "kind": _kind(e), "allowed": allowed(e)}
        is_gated = False
        if state != "default" and not problems:
            try:
                is_gated = gated(e, typed(e, values[e.key]))
            except ValueError:
                pass
        item["gated"] = is_gated
        item["editable"] = not problems and not is_unknown(e) and not is_gated
        if is_unknown(e):
            item["reason"] = "no reader found: probably a stale name; only removal is offered"
        elif is_gated:
            item["reason"] = "gated by ADR-0011: change by hand only after its evaluation; only removal is offered"
        if not problems and not is_secret(e) and e.key in values:
            item["value"] = values[e.key]
        groups.setdefault(_group_name(e), []).append(item)
    tail = {"Study and ops (leafi)": 1, "Habit agent": 2, "Compose only": 3, "Unknown": 4}
    names = sorted(groups, key=lambda n: (n in tail, tail.get(n, 0), order.get(n, 0)))
    body = {"digest": digest, "groups": [{"name": n, "keys": groups[n]} for n in names]}
    if problems:
        body["problems"] = [{"line": p.line, "key": p.key, "rule": p.rule} for p in problems]
    return body


# ---------------------------------------------------------------- save


class BadRequest(ValueError):
    pass


class Rejected(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("rejected")
        self.errors = errors


@dataclass
class SaveResult:
    status: int
    body: dict


def confirmation(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_ops(body: Any) -> tuple[str, dict[str, Op], dict[str, str]]:
    if not isinstance(body, dict) or set(body) - {"digest", "ops", "confirm"}:
        raise BadRequest("body must be {digest, ops, confirm}")
    digest, raw_ops, confirm = body.get("digest"), body.get("ops"), body.get("confirm", {})
    if not isinstance(digest, str) or not isinstance(raw_ops, dict) or not isinstance(confirm, dict):
        raise BadRequest("digest must be a string, ops and confirm objects")
    ops: dict[str, Op] = {}
    for key, spec in raw_ops.items():
        if not isinstance(key, str) or not re.fullmatch(envfile.KEY, key) or not isinstance(spec, dict):
            raise BadRequest("bad key or op")
        kind = spec.get("op")
        if set(spec) - {"op", "value"} or kind not in ("set", "empty", "unset"):
            raise BadRequest("op must be set, empty or unset")
        if kind == "set":
            if not isinstance(spec.get("value"), str):
                raise BadRequest("set requires a string value")
            ops[key] = Op("set", spec["value"])
        else:
            if "value" in spec:
                raise BadRequest(f"{kind} takes no value")
            ops[key] = Op(kind)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in confirm.items()):
        raise BadRequest("confirm must map keys to strings")
    return digest, ops, confirm


def _file_only(cls):
    """A validation-only subclass that reads nothing but its init arguments (no environment, no .env)."""

    class FileOnly(cls):
        @classmethod
        def settings_customise_sources(cls_, settings_cls, init_settings, env_settings, dotenv_settings,
                                       file_secret_settings):
            return (init_settings,)

    return FileOnly


def _validate_whole(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    errors: dict[str, str] = {}
    warnings: list[str] = []
    instances = {}
    for reader, cls in ((READER_LEAFI, LeafiSettings), (READER_HABIT, _habit_settings_class())):
        kwargs = {k.lower(): v for k, v in values.items() if k.lower() in cls.model_fields}
        try:
            instances[reader] = _file_only(cls)(**kwargs)
        except ValidationError as err:
            for e in err.errors():
                errors[str(e["loc"][0]).upper() if e["loc"] else "*"] = e["msg"]
    if READER_LEAFI in instances:
        from leafi.ops import timing

        _, problems = timing.resolve(instances[READER_LEAFI])
        warnings += [f"supervision timing: {p} conflicts, its defaults will be used (python -m leafi timing)"
                     for p in problems]
    return errors, warnings


def save(body: Any, path: Path = Path(".env"), data_dir: Path = Path("data"), root: Path = ROOT,
         trusted_confirm: bool = False) -> SaveResult:
    """Validate and write one batch of ops (all or nothing). `trusted_confirm`: the caller (the CLI) is itself the
    owner's explicit confirmation for privacy keys."""
    try:
        digest, ops, confirm = parse_ops(body)
    except BadRequest as e:
        return SaveResult(400, {"ok": False, "error": str(e)})
    warnings: list[str] = []

    def transform(old: bytes) -> bytes:
        f = EnvFile.parse(old)
        if f.problems():
            raise Rejected({"*": "file is not canonical; fix the listed lines by hand, then reload"})
        current = f.values()
        cat = catalog(set(current), root)
        errors: dict[str, str] = {}
        for key, op in ops.items():
            e = cat.entries.get(key)
            if e is None:
                errors[key] = "not a known setting"
                continue
            now_gated = False
            if key in current:
                try:
                    now_gated = gated(e, typed(e, current[key]))
                except ValueError:
                    pass
            if (is_unknown(e) or now_gated) and op.kind != "unset":
                errors[key] = "only removal is offered for this setting"
                continue
            new_text = op.value if op.kind == "set" else ""
            if op.kind != "unset":
                try:
                    value = typed(e, new_text)
                except ValueError as err:
                    errors[key] = str(err)
                    continue
                if gated(e, value):
                    errors[key] = "gated by ADR-0011: not settable from this page"
                    continue
                options = allowed(e)
                if options is not None and new_text != "" and new_text not in options:
                    errors[key] = "not an allowed value: " + ", ".join(options)
                    continue
            changes = (current.get(key) != new_text) if op.kind != "unset" else key in current
            if e.privacy and changes and not trusted_confirm and confirm.get(key) != confirmation(new_text):
                errors[key] = "privacy setting: confirm this exact value"
        if errors:
            raise Rejected(errors)
        try:
            new = f.apply(ops, cat.anchors)
        except Unstorable as err:
            raise Rejected({err.key: "cannot be stored so that every reader reads the same text; edit by hand"})
        whole_errors, whole_warnings = _validate_whole(new.values())
        if whole_errors:
            raise Rejected(whole_errors)
        warnings.extend(whole_warnings)
        shadowed = env_overrides(list(ops))
        warnings.extend(f"this process has {k} set in its environment; a service started the same way ignores the "
                        f"file value" for k in shadowed)
        return new.render()

    try:
        outcome = envfile.update_env(Path(path), digest, transform, Path(data_dir))
    except Rejected as r:
        return SaveResult(200, {"ok": False, "errors": r.errors})
    except TimeoutError:
        return SaveResult(409, {"ok": False, "error": "another save is in progress"})
    except OSError as e:
        log.warning("save failed: %s", e.__class__.__name__)
        return SaveResult(200, {"ok": False, "errors": {"*": f"could not write ({e.__class__.__name__})"}})
    if isinstance(outcome, Conflict):
        return SaveResult(409, {"ok": False, "error": "changed on disk"})
    if isinstance(outcome, RecoveryRequired):
        return SaveResult(500, {"ok": False, "recovery": outcome.paths})
    if isinstance(outcome, Committed):
        cat = catalog(root=root)
        acts = sorted({a for k in ops if (e := cat.entries.get(k)) for r in e.readers if (a := activation(r))})
        log.info("saved .env keys: %s", ", ".join(sorted(ops)))
        return SaveResult(200, {"ok": True, "digest": outcome.digest, "activation": acts,
                                "warnings": warnings + outcome.warnings})
    return SaveResult(200, {"ok": False, "errors": {"*": outcome.reason}, "warnings": outcome.warnings})


def current_digest(path: Path = Path(".env")) -> str:
    return envfile.read_state(Path(path))[1]


__all__ = ["ABSENT", "catalog", "view", "save", "confirmation", "current_digest", "SaveResult"]
