"""Change the condition tags (tags.json) and move the labels already given in Label Studio with them.

    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py                    # menu (the console's button)
    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py list               # groups, options, how often each is used
    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py add GROUP OPTION...           [--yes]
    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py rename GROUP OLD NEW          [--yes]
    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py rename-group OLD NEW          [--yes]
    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py remove GROUP OPTION (--to OTHER | --clear) [--yes]
    .venv-eval\\Scripts\\python scripts/evals/ocr/tags.py remove-group GROUP            [--yes]

Without --yes a command only prints what it would change. With it: every annotation is saved to
cache/evals/ocr/backups/ first; then Label Studio gets a config holding both the old and the new tags (it refuses
a config that drops a choice still used), the annotations are rewritten, the final config is set, and tags.json
and synthetic.json are updated last. `labels.py pull` afterwards gives truth.json the new names. MLflow keeps
the old per-tag metric names on runs made before the change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evalenv  # noqa: E402
import labels  # noqa: E402

RESERVED = {"page_id", "page_text", "page_number", "label", "bbox", "transcription", "image", "source"}
KEPT = {"angle": {"0", "90", "180", "270"}}  # run.py turns these into the expected rotation
NAME = re.compile(r"[a-z][a-z0-9_]*")


class Refused(Exception):
    pass


def check_group(name: str, tags: dict) -> None:
    if not NAME.fullmatch(name) or name in RESERVED:
        raise Refused(f"group name '{name}': use lower-case letters, digits, _; not one of {sorted(RESERVED)}")
    if name in tags:
        raise Refused(f"group '{name}' already exists")


def check_option(group: str, value: str, tags: dict) -> None:
    if not value.strip() or any(c in value for c in '"<>&'):
        raise Refused(f"option '{value}': not empty, and no \" < > &")
    if value in tags.get(group, []):
        raise Refused(f"'{group}' already has '{value}'")


def need(tags: dict, group: str, value: str | None = None) -> None:
    if group not in tags:
        raise Refused(f"no group '{group}'; groups: {', '.join(tags)}")
    if value is not None and value not in tags[group]:
        raise Refused(f"'{group}' has no '{value}'; options: {', '.join(tags[group])}")
    if value in KEPT.get(group, ()) or (value is None and group in KEPT):
        raise Refused(f"run.py reads '{group}' {sorted(KEPT[group])}; keep them")


# A change = the new tags plus a map (group, value) -> (group, value), or None to drop the label.
def plan(cmd: str, a: list[str], to: str | None, clear: bool, tags: dict):
    new = {g: list(v) for g, v in tags.items()}
    if cmd == "add":
        group, values = a[0], a[1:]
        if not values:
            raise Refused("add GROUP OPTION...: give at least one option")
        if group not in tags:
            check_group(group, tags)
            new[group] = []
        for v in values:
            check_option(group, v, new)
            new[group].append(v)
        return new, lambda g, v: (g, v), f"add to '{group}': {', '.join(values)}"
    if cmd == "rename":
        group, old, value = a
        need(tags, group, old)
        check_option(group, value, tags)
        new[group] = [value if v == old else v for v in new[group]]
        return new, lambda g, v: (g, value) if (g, v) == (group, old) else (g, v), f"'{group}': '{old}' → '{value}'"
    if cmd == "rename-group":
        old, group = a
        need(tags, old)
        check_group(group, tags)
        new = {group if g == old else g: v for g, v in new.items()}
        return new, lambda g, v: (group if g == old else g, v), f"group '{old}' → '{group}'"
    if cmd == "remove":
        group, old = a
        need(tags, group, old)
        if clear == (to is not None):
            raise Refused("remove GROUP OPTION needs --to OTHER (move its labels) or --clear (leave them unset)")
        if to is not None and (to == old or to not in tags[group]):
            raise Refused(f"--to: one of the other options of '{group}': {', '.join(o for o in tags[group] if o != old)}")
        new[group].remove(old)
        if len(new[group]) < 2:
            raise Refused(f"'{group}' would keep fewer than two options; remove the group instead")
        move = None if clear else (group, to)
        how = "left unset" if clear else f"moved to '{to}'"
        return new, lambda g, v: move if (g, v) == (group, old) else (g, v), f"remove '{group}': '{old}' (labels {how})"
    if cmd == "remove-group":
        (group,) = a
        need(tags, group)
        del new[group]
        return new, lambda g, v: None if g == group else (g, v), f"remove group '{group}' and its labels"
    raise Refused(f"unknown command {cmd}")


def union(old: dict, new: dict) -> dict:
    out = {g: list(v) for g, v in old.items()}
    for g, vals in new.items():
        out.setdefault(g, [])
        out[g] += [v for v in vals if v not in out[g]]
    return out


def rewrite(result: list[dict], tags: dict, move) -> list[dict] | None:
    """The annotation's result with tags moved, or None when nothing in it changes."""
    out, changed = [], False
    for r in result:
        if r.get("type") == "choices" and r.get("from_name") in tags and r["value"].get("choices"):
            to = move(r["from_name"], r["value"]["choices"][0])
            if to != (r["from_name"], r["value"]["choices"][0]):
                changed = True
                if to is None:
                    continue
                r = {**r, "from_name": to[0], "value": {**r["value"], "choices": [to[1]]}}
        out.append(r)
    return out if changed else None


def usage(tasks: list[dict], tags: dict) -> dict:
    count = {(g, v): 0 for g, vals in tags.items() for v in vals}
    for t in tasks:
        for a in t.get("annotations") or []:
            for r in a["result"]:
                if r.get("type") == "choices" and r.get("from_name") in tags and r["value"].get("choices"):
                    key = (r["from_name"], r["value"]["choices"][0])
                    count[key] = count.get(key, 0) + 1
    return count


def show(tags: dict, count: dict) -> None:
    for g, vals in tags.items():
        print(f"  {g}: " + ", ".join(f"{v} ({count.get((g, v), 0)})" for v in vals))


def apply(ls, p: dict, tasks: list[dict], tags: dict, new: dict, move, yes: bool) -> None:
    edits = [(a["id"], res) for t in tasks for a in t.get("annotations") or []
             if (res := rewrite(a["result"], tags, move)) is not None]
    synthetic_path = evalenv.DATA / "synthetic.json"
    synthetic = json.loads(synthetic_path.read_text(encoding="utf-8")) if synthetic_path.exists() else []
    for m in synthetic:
        for g in list(m):
            if g in tags:
                to = move(g, m.pop(g))
                if to is not None:
                    m[to[0]] = to[1]
    print(f"{len(edits)} annotation(s) to rewrite in project '{labels.TITLE}'")
    if not yes:
        print("Nothing changed (add --yes to apply).")
        return
    backups = evalenv.DATA / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"annotations-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps({"tags": tags, "tasks": [{"id": t["id"], "file": t["data"].get("file"),
                                                          "annotations": t.get("annotations") or []} for t in tasks]},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"backup: {backup}")
    ls("PATCH", f"/api/projects/{p['id']}", json={"label_config": labels.config(union(tags, new))})
    for aid, res in edits:
        ls("PATCH", f"/api/annotations/{aid}", json={"result": res})
    ls("PATCH", f"/api/projects/{p['id']}", json={"label_config": labels.config(new)})
    evalenv.TAGS_FILE.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if synthetic:
        synthetic_path.write_text(json.dumps(synthetic, indent=1), encoding="utf-8")
    print(f"done: {evalenv.TAGS_FILE.name} and Label Studio updated; run labels-pull to refresh truth.json")


def menu(ls, p: dict, tasks: list[dict], tags: dict) -> None:
    print("Tags now (labels given):")
    show(tags, usage(tasks, tags))
    print("\n  1 add options or a new group   2 rename an option   3 rename a group"
          "\n  4 remove an option            5 remove a group     (Enter = quit)")
    pick = input("> ").strip()
    if not pick:
        return
    ask = lambda q: input(q + ": ").strip()  # noqa: E731
    to, clear = None, False
    if pick == "1":
        cmd, a = "add", [ask("group (existing or new)")] + [v.strip() for v in ask("options, comma-separated").split(",")]
    elif pick == "2":
        cmd, a = "rename", [ask("group"), ask("old option"), ask("new option")]
    elif pick == "3":
        cmd, a = "rename-group", [ask("old group"), ask("new group")]
    elif pick == "4":
        cmd, a = "remove", [ask("group"), ask("option")]
        to = ask("move its labels to which option (Enter = leave them unset)") or None
        clear = to is None
    elif pick == "5":
        cmd, a = "remove-group", [ask("group")]
    else:
        raise Refused(f"no choice {pick}")
    new, move, what = plan(cmd, [x for x in a if x], to, clear, tags)
    print(what)
    apply(ls, p, tasks, tags, new, move, yes=False)
    if input("Apply? [y/N] ").strip().lower() == "y":
        apply(ls, p, tasks, tags, new, move, yes=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", choices=["list", "add", "rename", "rename-group", "remove", "remove-group"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--to")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--yes", action="store_true")
    o = ap.parse_args()
    tags = evalenv.tags()
    ls = labels.LS()
    p = labels.project(ls)
    tasks = labels.tasks(ls, p["id"])
    try:
        if o.cmd is None:
            menu(ls, p, tasks, tags)
        elif o.cmd == "list":
            show(tags, usage(tasks, tags))
        else:
            arity = {"rename": 3, "rename-group": 2, "remove": 2, "remove-group": 1}.get(o.cmd)
            if arity is not None and len(o.args) != arity:
                raise Refused(f"{o.cmd} takes {arity} argument(s)")
            new, move, what = plan(o.cmd, o.args, o.to, o.clear, tags)
            print(what)
            apply(ls, p, tasks, tags, new, move, o.yes)
    except Refused as e:
        print(f"refused: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
