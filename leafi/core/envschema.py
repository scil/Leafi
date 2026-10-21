"""The `.env` settings manifest, `config/env-schema.json` (design rev 8: docs/plans/active/2026-10-21-env-settings-page.md).

The manifest is the one description of what `.env` may hold: group, order, type, options, readers, defaults per
reader, help, secret / privacy flags, release gates, validators and the `.env.example` line. The Settings classes keep
their fields (what each process runs with); `leafi.envedit.agreement` checks the two agree. This loader only parses
and checks the manifest's own shape; standard library only, never imported by a service at start.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TYPES = ("text", "secret", "int", "float", "bool", "path", "enum", "list")
EMPTY_RULES = ("empty", "default", "error", "current-dir", "disables-device")
SEVERITIES = ("error", "warning")
PATH = Path(__file__).resolve().parents[2] / "config" / "env-schema.json"


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class ReaderDefault:
    value: str
    empty: str
    absent: str | None = None


@dataclass(frozen=True)
class Validator:
    fn: str
    severity: str
    consumer: str


@dataclass(frozen=True)
class Key:
    name: str
    group: str
    type: str
    readers: tuple[str, ...]
    help: str = ""
    options: tuple[str, ...] | None = None
    domain: str | None = None
    default: dict[str, ReaderDefault] = field(default_factory=dict)
    secret: bool = False
    privacy: bool = False
    gate_values: tuple[str, ...] = ()
    gate_nonempty: bool = False
    validator: Validator | None = None
    example: str | None = None
    example_commented: bool = False
    notes: tuple[str, ...] = ()  # comment lines written above the key in .env.example
    notes_after: tuple[str, ...] = ()


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Manifest:
    readers: dict[str, str]  # reader -> activation action
    groups: tuple[Group, ...]  # in order
    keys: dict[str, Key]  # insertion order = page and .env.example order

    def group_title(self, gid: str) -> str:
        return next(g.title for g in self.groups if g.id == gid)


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise SchemaError(msg)


def parse(data: dict) -> Manifest:
    _need(isinstance(data, dict) and data.get("version") == 1, "version must be 1")
    readers = {}
    for name, spec in (data.get("readers") or {}).items():
        _need(isinstance(spec, dict) and isinstance(spec.get("action"), str) and spec["action"],
              f"reader {name}: needs an action")
        readers[name] = spec["action"]
    groups = tuple(Group(g["id"], g["title"], tuple(g.get("notes") or ())) for g in data.get("groups") or [])
    _need(len({g.id for g in groups}) == len(groups), "duplicate group id")
    gids = {g.id for g in groups}
    _need(all("\n" not in n for g in groups for n in g.notes), "a group note has a newline")
    keys: dict[str, Key] = {}
    for name, spec in (data.get("keys") or {}).items():
        where = f"key {name}"
        _need(isinstance(spec, dict), f"{where}: not an object")
        _need(spec.get("group") in gids, f"{where}: unknown group")
        t = spec.get("type")
        _need(t in TYPES, f"{where}: unknown type {t!r}")
        rs = tuple(spec.get("readers") or ())
        _need(all(r in readers for r in rs), f"{where}: a reader has no activation entry")
        options = spec.get("options")
        if t in ("enum", "list"):
            _need(isinstance(options, list) and options and all(isinstance(o, str) for o in options),
                  f"{where}: {t} needs options")
            _need(isinstance(spec.get("domain"), str), f"{where}: {t} needs a domain")
            if t == "list":
                _need(all("," not in o and " " not in o for o in options), f"{where}: list options contain ',' or ' '")
        else:
            _need(options is None, f"{where}: options only for enum and list")
        default = {}
        for r, d in (spec.get("default") or {}).items():
            _need(r in rs, f"{where}: default for a reader it does not list")
            _need(isinstance(d.get("value"), str) and d.get("empty") in EMPTY_RULES
                  and d.get("absent") in (None, *EMPTY_RULES), f"{where}: bad default for {r}")
            default[r] = ReaderDefault(d["value"], d["empty"], d.get("absent"))
        gate = spec.get("gate") or {}
        _need(set(gate) <= {"values", "nonempty"}, f"{where}: unknown gate field")
        gvalues = tuple(gate.get("values") or ())
        if t in ("enum", "list"):
            _need(set(gvalues) <= set(options), f"{where}: gate value outside options")
        v = spec.get("validator")
        validator = None
        if v is not None:
            _need(isinstance(v, dict) and v.get("severity") in SEVERITIES
                  and all(isinstance(v.get(k), str) and ":" in v[k] for k in ("fn", "consumer"))
                  and v["fn"].startswith(("leafi.", "agent.")), f"{where}: bad validator")
            validator = Validator(v["fn"], v["severity"], v["consumer"])
        help_ = spec.get("help", "")
        _need(isinstance(help_, str) and "$" not in help_ and "\n" not in help_, f"{where}: help has '$' or a newline")
        ex = spec.get("example")
        keys[name] = Key(
            name=name, group=spec["group"], type=t, readers=rs, help=help_,
            options=tuple(options) if options else None, domain=spec.get("domain"), default=default,
            secret=bool(spec.get("secret")) or t == "secret", privacy=bool(spec.get("privacy")),
            gate_values=gvalues, gate_nonempty=bool(gate.get("nonempty")), validator=validator,
            example=ex["value"] if ex else None, example_commented=bool(ex and ex.get("commented")),
            notes=tuple(spec.get("notes") or ()), notes_after=tuple(spec.get("notes_after") or ()))
        _need(all("\n" not in n for n in keys[name].notes + keys[name].notes_after), f"{where}: a note has a newline")
    return Manifest(readers, groups, keys)


def load(path: Path = PATH) -> Manifest:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SchemaError(f"cannot read {Path(path).name}: {e.__class__.__name__}") from None
    return parse(data)
