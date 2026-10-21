"""The `.env` settings page's rules and the save coordinator (design rev 8: docs/plans/active/2026-10-21-env-settings-page.md).

Everything descriptive about a key comes from the manifest, `config/env-schema.json` (`leafi.core.envschema`).
`agreement()` checks the manifest against the code that really reads `.env` (both Settings classes, Compose, the
devices.yml expansion, the timing script, each choice list's domain constant, each validator's consumer) and against
the protection floor in `leafi.envprotect`; the tests and the editor both run it, services never do. Values are never
logged; secret values never leave this module except into the file.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from leafi import envprotect
from leafi.core import envfile, envschema
from leafi.core.config import Settings as LeafiSettings
from leafi.core.config import env_overrides
from leafi.core.envfile import Committed, Conflict, EnvFile, Op, RecoveryRequired, Unstorable
from leafi.core.envschema import Key, Manifest, SchemaError

log = logging.getLogger("leafi.envedit")

ROOT = Path(__file__).resolve().parents[1]
READER_LEAFI, READER_HABIT = "leafi", "habit agent"
TYPE_ANNOTATIONS = {"text": str, "secret": str, "enum": str, "list": str, "int": int, "float": float, "bool": bool,
                    "path": Path}
REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?:(:?-)([^}]*))?\}")


def _habit_settings_class():
    from agent.config import Settings

    return Settings


def settings_classes() -> dict[str, Any]:
    return {READER_LEAFI: LeafiSettings, READER_HABIT: _habit_settings_class()}


def _resolve(ref: str) -> Any:
    module, _, attr = ref.partition(":")
    obj = importlib.import_module(module)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def show(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Path):
        return v.as_posix()
    return str(v)


def empty_rule(annotation: Any) -> str:
    """What a Settings field does with `KEY=` (pydantic-settings 2.14 reads the empty string)."""
    try:
        v = TypeAdapter(annotation).validate_strings("")
    except ValidationError:
        return "error"
    return "current-dir" if isinstance(v, Path) else "empty"


# ---------------------------------------------------------------- typed values, gates, lists


def typed(k: Key, text: str) -> Any:
    """The value the first Settings reader would hold; raises ValueError naming the rule, never the value."""
    for reader, cls in settings_classes().items():
        if reader in k.readers:
            try:
                return TypeAdapter(cls.model_fields[k.name.lower()].annotation).validate_strings(text)
            except ValidationError as err:
                raise ValueError(err.errors()[0]["msg"]) from None
    return text


def gated(k: Key, text: str) -> bool:
    if k.gate_nonempty and text != "":
        return True
    if not k.gate_values:
        return False
    if k.type == "list":
        return any(item in k.gate_values for item in text.split(",") if item)
    try:
        value = typed(k, text)
        return any(value == typed(k, g) for g in k.gate_values)
    except ValueError:
        return False


def offered(k: Key) -> list[str] | None:
    """The options the page offers: every option the code knows (true/false for a bool), minus the gated ones."""
    options = ("true", "false") if k.type == "bool" else k.options
    if options is None:
        return None
    return [o for o in options if not gated(k, o)]


def masked(k: Key) -> bool:
    """Secret by the manifest, by the protection floor, or by its name: the floor holds even if the manifest is weakened."""
    return k.secret or k.name in envprotect.SECRET_FLOOR or bool(re.search(envprotect.CREDENTIAL_NAME, k.name))


def normalise_list(k: Key, text: str) -> str:
    items = [i.strip() for i in text.split(",") if i.strip()]
    if len(set(items)) != len(items):
        raise ValueError("an item is repeated")
    unknown = [i for i in items if i not in k.options]
    if unknown:
        raise ValueError("not an allowed item: choose from " + ", ".join(k.options))
    return ",".join(o for o in k.options if o in items)


# ---------------------------------------------------------------- agreement (the tests and the editor run this)


def _compose_refs(root: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """(key, "compose:<svc>") -> (default value, empty rule), from docker-compose.yml."""
    import yaml

    out = {}
    services = (yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8")) or {}).get("services", {})
    for svc, spec in services.items():
        for m in REF.finditer(yaml.safe_dump(spec)):
            op, value = m.group(2), m.group(3) or ""
            rule = "default" if op == ":-" else "empty"
            out[(m.group(1), f"compose:{svc}")] = (value if op else "", rule)
    return out


def _device_refs(root: Path) -> dict[tuple[str, str], tuple[str, str, str]]:
    """(key, "devices.yml:<device>.<option>[#n]") -> (default, empty rule, absent rule), derived by calling the
    hub's own `_expand` on each reference alone, with every other variable set to a sentinel."""
    import yaml

    from leafi.core.hub import _VAR_RE, _expand

    out = {}
    data = yaml.safe_load((root / "config" / "devices.yml").read_text(encoding="utf-8")) or {}
    for d in data.get("devices") or []:
        for opt, val in (d.get("options") or {}).items():
            if not isinstance(val, str):
                continue
            seen: dict[str, int] = {}
            for m in _VAR_RE.finditer(val):
                key = m.group(1)
                seen[key] = seen.get(key, 0) + 1
                reader = f"devices.yml:{d['name']}.{opt}" + (f"#{seen[key]}" if seen[key] > 1 else "")

                def rule(test_value: str | None) -> tuple[str, str]:
                    missing: list[str] = []
                    got = _expand(m.group(0), lambda n: test_value if n == key else "SENTINEL", missing)
                    return got, ("disables-device" if key in missing else "default" if got else "empty")

                default, empty = rule("")
                _, absent = rule(None)
                out[(key, reader)] = (default, empty, absent)
    return out


def _secret_name(m: Manifest, name: str) -> bool:
    k = m.keys.get(name)
    return (k is not None and masked(k)) or name in envprotect.SECRET_FLOOR or bool(re.search(envprotect.CREDENTIAL_NAME, name))


def agreement(m: Manifest, root: Path = ROOT) -> list[str]:
    """Every way the manifest disagrees with the code, the readers or the protection floor; [] = agree. The messages
    reach the page, so a secret key's default or fallback value is never quoted in them."""
    out: list[str] = []
    classes = settings_classes()

    def q(name: str, value: str) -> str:
        return "<secret>" if _secret_name(m, name) else repr(value)

    # Settings fields, types and defaults, both ways
    for reader, cls in classes.items():
        for fname, f in cls.model_fields.items():
            k = m.keys.get(fname.upper())
            if k is None or reader not in k.readers:
                out.append(f"{fname.upper()}: read by {reader} but not declared for it")
                continue
            if TYPE_ANNOTATIONS[k.type] is not f.annotation:
                out.append(f"{k.name}: type {k.type} does not match {reader}'s {f.annotation}")
            want = (show(f.default), empty_rule(f.annotation))
            got = k.default.get(reader)
            if got is None or (got.value, got.empty) != want:
                out.append(f"{k.name}: default for {reader} should be {q(k.name, want[0])} (empty: {want[1]})")
    for k in m.keys.values():
        for reader, cls in classes.items():
            if reader in k.readers and k.name.lower() not in cls.model_fields:
                out.append(f"{k.name}: says {reader} reads it, but {reader} has no such field")

    # Compose, both ways
    compose = _compose_refs(root)
    for (key, reader), (value, rule) in compose.items():
        k = m.keys.get(key)
        d = k.default.get(reader) if k else None
        if k is None or reader not in k.readers or d is None or (d.value, d.empty) != (value, rule):
            out.append(f"{key}: {reader} reads it with default {q(key, value)} (empty: {rule}); declare exactly that")
    for k in m.keys.values():
        for r in k.readers:
            if r.startswith("compose:") and (k.name, r) not in compose:
                out.append(f"{k.name}: says {r} reads it, but docker-compose.yml has no such reference")

    # devices.yml, both ways
    devices = _device_refs(root)
    for (key, reader), (value, rule, absent) in devices.items():
        k = m.keys.get(key)
        d = k.default.get(reader) if k else None
        want_absent = absent if absent != rule else None
        if k is None or reader not in k.readers or d is None or (d.value, d.empty, d.absent) != (value, rule, want_absent):
            out.append(f"{key}: {reader} reads it with default {q(key, value)} (empty: {rule}, absent: {absent})")
    for k in m.keys.values():
        for r in k.readers:
            if r.startswith("devices.yml:") and (k.name, r) not in devices:
                out.append(f"{k.name}: says {r} reads it, but config/devices.yml has no such reference")

    # Gatus and Frigate YAML read the container environment that their own Compose service builds
    for svc, files in (("gatus", [root / "config" / "gatus" / "config.yaml"]),
                       ("frigate", sorted((root / "config" / "frigate").glob("*.yml")))):
        for f in files:
            if f.exists():
                text = "\n".join(ln for ln in f.read_text(encoding="utf-8").splitlines()
                                 if not ln.lstrip().startswith("#"))
                for ref in REF.finditer(text):
                    k = m.keys.get(ref.group(1))
                    if k is None or f"compose:{svc}" not in k.readers:
                        out.append(f"{ref.group(1)}: used in {f.name} but compose:{svc} does not pass it")

    # timing.ps1's fallback table equals the leafi defaults
    ps1 = root / "scripts" / "win" / "timing.ps1"
    if ps1.exists():
        for key, value in re.findall(r"\b((?:KEEP|TASK)_[A-Z_]+) = \"([^\"]*)\"", ps1.read_text(encoding="utf-8")):
            k = m.keys.get(key)
            d = k.default.get(READER_LEAFI) if k else None
            if d is None:
                out.append(f"{key}: in timing.ps1 but not a leafi setting")
            else:
                try:
                    same = typed(k, value) == typed(k, d.value)
                except ValueError:
                    same = False
                if not same:
                    out.append(f"{key}: timing.ps1 falls back to {q(key, value)}, leafi's default is {q(key, d.value)}")
            reader = "logon task" if key == "TASK_REPEAT_MIN" else "keep.ps1"
            if k is not None and reader not in k.readers:
                out.append(f"{key}: {reader} reads it (activation) but it is not declared")

    # choice lists against the code that consumes them; gates
    for k in m.keys.values():
        if k.domain:
            try:
                dom = _resolve(k.domain)
            except (ImportError, AttributeError):
                out.append(f"{k.name}: domain {k.domain} does not resolve")
                continue
            values = set(dom.backends) | set(dom.deferred) if hasattr(dom, "backends") else set(dom)
            if set(k.options) != values:
                out.append(f"{k.name}: options {sorted(k.options)} differ from {k.domain} {sorted(values)}")
            if hasattr(dom, "deferred") and not set(dom.deferred) <= set(k.gate_values):
                out.append(f"{k.name}: deferred backends must be gated")
        for g in k.gate_values:
            try:
                typed(k, g)
            except ValueError:
                out.append(f"{k.name}: gate value {g!r} is not a valid value")

    # validators: resolve, and accept every example and default of their key
    for k in m.keys.values():
        if k.validator is None:
            continue
        try:
            fn = _resolve(k.validator.fn)
            _resolve(k.validator.consumer)
        except (ImportError, AttributeError):
            out.append(f"{k.name}: validator or consumer does not resolve")
            continue
        texts = [d.value for r, d in k.default.items() if r in (READER_LEAFI, READER_HABIT)]
        if k.example is not None and not k.example_commented:
            texts.append(k.example)
        for t in texts:
            try:
                fn(t)
            except ValueError:
                out.append(f"{k.name}: its validator rejects its own default or example")

    # examples: needed where readers disagree or there is no default; never gated, privacy opt-ins stay off
    for k in m.keys.values():
        values = {d.value for d in k.default.values()}
        if k.example is None and len(values) != 1:
            out.append(f"{k.name}: needs an explicit example (readers' defaults differ or there is none)")
        if k.example is not None and not k.example_commented:
            try:
                EnvFile.encode(k.name, k.example, True)
            except Unstorable:
                out.append(f"{k.name}: example cannot be stored canonically")
            if gated(k, k.example):
                out.append(f"{k.name}: active example sets a gated value")
            if k.type == "enum" and k.example != "" and k.example not in k.options:
                out.append(f"{k.name}: active example is not one of its options")
            if k.type == "list" and k.example != "":
                try:
                    if normalise_list(k, k.example) != k.example:
                        out.append(f"{k.name}: active example is not written in options order")
                except ValueError:
                    out.append(f"{k.name}: active example has an item outside its options")
            if k.privacy and k.example not in values:
                out.append(f"{k.name}: privacy key's active example must equal its default")

    # protection floor and the credential name rule
    for key in envprotect.SECRET_FLOOR:
        if key not in m.keys or not m.keys[key].secret:
            out.append(f"{key}: must be secret (leafi/envprotect.py)")
    for key in envprotect.PRIVACY_FLOOR:
        if key not in m.keys or not m.keys[key].privacy:
            out.append(f"{key}: must be a privacy key (leafi/envprotect.py)")
    for key, value in envprotect.GATE_FLOOR:
        k = m.keys.get(key)
        if k is None or not (k.gate_nonempty if value == "*" else gated(k, value)):
            out.append(f"{key}={value}: must be gated (leafi/envprotect.py)")
    for k in m.keys.values():
        if re.search(envprotect.CREDENTIAL_NAME, k.name) and not k.secret:
            out.append(f"{k.name}: its name looks like a credential; mark it secret")
    return out


# ---------------------------------------------------------------- .env.example


def env_example(m: Manifest) -> bytes:
    """The `.env.example` the manifest describes (canonical by construction)."""
    lines: list[str] = []
    for g in m.groups:
        keys = [k for k in m.keys.values() if k.group == g.id]
        if not keys:
            continue
        if lines:
            lines.append("")
        lines.append(f"# ===== {g.title} =====")
        lines += [f"# {n}" for n in g.notes]
        for k in keys:
            lines += [f"# {n}" for n in k.notes]
            if k.example is not None:
                value, commented = k.example, k.example_commented
            else:
                value = next(iter(k.default.values())).value if k.default else ""
                commented = True
            assign = f"{k.name}={EnvFile.encode(k.name, value, bool(k.help))}"
            line = ("# " if commented else "") + assign
            if k.help:
                line += " " * max(3, 33 - len(line)) + "# " + k.help
            lines.append(line)
            lines += [f"# {n}" for n in k.notes_after]
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------- the GET body


def load(root: Path = ROOT) -> tuple[Manifest | None, list[str]]:
    """The manifest and its disagreements; (None, [error]) when it does not even load."""
    try:
        m = envschema.load(root / "config" / "env-schema.json")
    except SchemaError as e:
        return None, [f"manifest: {e}"]
    return m, agreement(m, root)


def _empty_notes(k: Key) -> list[str]:
    notes = []
    for r, d in k.default.items():
        if d.empty == "default":
            notes.append(f"{r} uses its built-in fallback" if masked(k) else f"{r} uses {d.value!r}")
        elif d.empty == "disables-device":
            notes.append(f"{r}: the device is disabled")
        elif d.empty == "current-dir":
            notes.append(f"{r} reads the current directory")
    return notes


def view(path: Path = Path(".env"), root: Path = ROOT) -> dict:
    raw, digest = envfile.read_state(Path(path))
    m, mismatches = load(root)
    if m is None:
        return {"digest": digest, "manifest_error": mismatches[0], "groups": []}
    f = EnvFile.parse(raw)
    problems = f.problems()
    # a disagreeing manifest may have lost a protection: show no values at all until it is fixed
    values = {} if problems else f.values()
    shown = {} if mismatches else values
    locked = bool(problems or mismatches)
    groups: list[dict] = []
    for g in m.groups:
        items = []
        for k in (k for k in m.keys.values() if k.group == g.id):
            state = "default" if k.name not in values else ("empty" if values[k.name] == "" else "set")
            is_gated = state != "default" and gated(k, values[k.name])
            item = {"key": k.name, "state": state, "type": k.type, "help": k.help, "readers": list(k.readers),
                    "defaults": {r: {"value": "" if masked(k) else d.value, "empty": d.empty}
                                 for r, d in k.default.items()},
                    "activation": sorted({m.readers[r] for r in k.readers}), "secret": masked(k),
                    "privacy": k.privacy, "options": offered(k), "gated": is_gated,
                    "empty_allowed": all(d.empty != "error" for d in k.default.values()),
                    "empty_notes": _empty_notes(k),
                    "editable": not locked and not is_gated}
            if is_gated:
                item["reason"] = "gated by ADR-0011: change by hand only after its evaluation; only removal is offered"
            if not k.readers:
                item["reason"] = "documented in .env.example; no program in this repository reads it"
            if not masked(k) and k.name in shown:
                item["value"] = shown[k.name]
            items.append(item)
        if items:
            groups.append({"name": g.title, "keys": items})
    unknown = sorted(set(values) - set(m.keys))
    if unknown:
        groups.append({"name": "Unknown", "keys": [
            {"key": u, "state": "empty" if values[u] == "" else "set", "type": "secret", "secret": True,
             "privacy": False, "readers": [], "defaults": {}, "activation": [], "options": None, "gated": False,
             "empty_allowed": False, "empty_notes": [], "editable": False,
             "reason": "no reader found: probably a stale name; only removal is offered", "help": ""}
            for u in unknown]})
    body = {"digest": digest, "groups": groups}
    if problems:
        body["problems"] = [{"line": p.line, "key": p.key, "rule": p.rule} for p in problems]
    if mismatches:
        body["agreement"] = mismatches
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


def validate_whole(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    errors: dict[str, str] = {}
    warnings: list[str] = []
    instances = {}
    for reader, cls in settings_classes().items():
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


def _check_op(k: Key, op: Op, current: dict[str, str], confirm: dict[str, str], trusted: bool,
              warnings: list[str]) -> tuple[Op | None, str | None]:
    """The op as it will be written (lists normalised), or an error naming the rule."""
    if k.name in current and gated(k, current[k.name]) and op.kind != "unset":
        return None, "only removal is offered for this setting"
    text = op.value if op.kind == "set" else ""
    if op.kind != "unset":
        if text == "" and not all(d.empty != "error" for d in k.default.values()):
            return None, "cannot be empty for every reader; use 'restore default' instead"
        if k.type == "list" and text != "":
            try:
                text = normalise_list(k, text)
            except ValueError as e:
                return None, str(e)
            op = Op("set", text)
        try:
            typed(k, text)
        except ValueError as e:
            return None, str(e)
        if k.validator is not None:
            try:
                _resolve(k.validator.fn)(text)
            except ValueError:
                msg = f"not accepted by {k.validator.fn}"
                if k.validator.severity == "error":
                    return None, msg
                warnings.append(f"{k.name}: {msg}; the running service falls back to its default")
        if gated(k, text):
            return None, "gated by ADR-0011: not settable from this page"
        if k.type == "enum" and text != "" and text not in (offered(k) or []):
            return None, "not an allowed value: " + ", ".join(offered(k) or [])
    changes = (current.get(k.name) != text) if op.kind != "unset" else k.name in current
    if k.privacy and changes and not trusted and confirm.get(k.name) != confirmation(text):
        return None, "privacy setting: confirm this exact value"
    return op, None


def save(body: Any, path: Path = Path(".env"), data_dir: Path = Path("data"), root: Path = ROOT,
         trusted_confirm: bool = False) -> SaveResult:
    """Validate and write one batch of ops (all or nothing). `trusted_confirm`: the caller (the CLI) is itself the
    owner's explicit confirmation for privacy keys."""
    try:
        digest, ops, confirm = parse_ops(body)
    except BadRequest as e:
        return SaveResult(400, {"ok": False, "error": str(e)})
    m, mismatches = load(root)
    if m is None or mismatches:
        return SaveResult(200, {"ok": False, "errors": {"*": "the settings manifest disagrees with the code; "
                                                              "the page is read-only until it is fixed"}})
    warnings: list[str] = []

    def transform(old: bytes) -> bytes:
        f = EnvFile.parse(old)
        if f.problems():
            raise Rejected({"*": "file is not canonical; fix the listed lines by hand, then reload"})
        current = f.values()
        errors: dict[str, str] = {}
        final: dict[str, Op] = {}
        for key, op in ops.items():
            k = m.keys.get(key)
            if k is None:
                if key in current and op.kind == "unset":
                    final[key] = op  # an Unknown key: removal only
                else:
                    errors[key] = "not a known setting" if key not in current else "only removal is offered"
                continue
            checked, err = _check_op(k, op, current, confirm, trusted_confirm, warnings)
            if err:
                errors[key] = err
            else:
                final[key] = checked
        if errors:
            raise Rejected(errors)
        anchors = {k.name: f"# ===== {m.group_title(k.group)} =====" for k in m.keys.values()}
        try:
            new = f.apply(final, anchors)
        except Unstorable as err:
            raise Rejected({err.key: "cannot be stored so that every reader reads the same text; edit by hand"})
        whole_errors, whole_warnings = validate_whole(new.values())
        if whole_errors:
            raise Rejected(whole_errors)
        warnings.extend(whole_warnings)
        warnings.extend(f"this process has {k} set in its environment; a service started the same way ignores the "
                        f"file value" for k in env_overrides(list(final)))
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
        acts = sorted({m.readers[r] for key in ops if key in m.keys for r in m.keys[key].readers})
        log.info("saved .env keys: %s", ", ".join(sorted(ops)))
        return SaveResult(200, {"ok": True, "digest": outcome.digest, "activation": acts,
                                "warnings": warnings + outcome.warnings})
    return SaveResult(200, {"ok": False, "errors": {"*": outcome.reason}, "warnings": outcome.warnings})


def current_digest(path: Path = Path(".env")) -> str:
    return envfile.read_state(Path(path))[1]
