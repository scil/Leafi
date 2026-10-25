"""Label Studio ↔ ground truth for the OCR evaluation trial.

    .venv-eval\\Scripts\\python scripts/evals/ocr/labels.py push   # project + one task per photo (new photos only)
    .venv-eval\\Scripts\\python scripts/evals/ocr/labels.py pull   # annotations → cache/evals/ocr/truth.json

The labeling view adds page-level fields to Label Studio's OCR template: the page's text (typed once per book
page: other photos of the same page give only the page id), the printed page number and the condition tags.
The template's boxes with per-box text stay available but are not needed for CER. Synthetic photos arrive
already annotated from synthetic.json. Talks only to http://localhost:19080 with the token from stack.env.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evalenv  # noqa: E402
import requests  # noqa: E402

TITLE = "Leafi OCR"
TAGS = {
    "angle": ["0", "90", "180", "270", "tilted"],
    "hand": ["none", "edge", "covering"],
    "desk": ["clean", "cluttered"],
    "light": ["normal", "dim", "glare"],
    "layout": ["plain", "decorative font", "text around picture", "spread"],
}
EXTS = {".jpg", ".jpeg", ".png"}


def config() -> str:
    choices = "\n".join(
        f'  <Header value="{k}"/>\n  <Choices name="{k}" toName="image" choice="single" showInline="true">\n'
        + "\n".join(f'    <Choice value="{v}"/>' for v in vals) + "\n  </Choices>"
        for k, vals in TAGS.items())
    return f"""<View>
  <Image name="image" value="$image" zoom="true" rotateControl="true"/>
  <Header value="Page id (book-page, for example zog-p12): the same id on every photo of the page"/>
  <TextArea name="page_id" toName="image" maxSubmissions="1" editable="true" rows="1"/>
  <Header value="Page text, line by line, without the page number (type it once per page id)"/>
  <TextArea name="page_text" toName="image" maxSubmissions="1" editable="true" rows="8"/>
  <Header value="Printed page number (empty if none or two)"/>
  <TextArea name="page_number" toName="image" maxSubmissions="1" editable="true" rows="1"/>
{choices}
  <Header value="Optional, from the OCR template: boxes with their text"/>
  <Labels name="label" toName="image"><Label value="Text" background="green"/></Labels>
  <Rectangle name="bbox" toName="image" strokeWidth="2"/>
  <TextArea name="transcription" toName="image" editable="true" perRegion="true" required="false"
            maxSubmissions="1" rows="2" placeholder="Text in this box"/>
</View>"""


class LS:
    def __init__(self) -> None:
        self.url = evalenv.local(evalenv.LABEL_STUDIO_URL)
        self.s = requests.Session()
        self.s.headers["Authorization"] = "Token " + evalenv.secrets()["LABEL_STUDIO_TOKEN"]

    def __call__(self, method: str, path: str, **kw):
        r = self.s.request(method, self.url + path, timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.content else None


def project(ls: LS) -> dict:
    found = [p for p in ls("GET", "/api/projects", params={"page_size": 100})["results"] if p["title"] == TITLE]
    if found:
        p = found[0]
        if p["label_config"].strip() != config().strip():
            ls("PATCH", f"/api/projects/{p['id']}", json={"label_config": config()})
        return p
    p = ls("POST", "/api/projects", json={"title": TITLE, "label_config": config(),
                                         "description": "Ground truth for Leafi's page OCR (local trial)"})
    ls("POST", "/api/storages/localfiles", json={"project": p["id"], "title": "photos", "path": "/photos/ocr",
                                                "use_blob_urls": False})
    return p


def text_value(name: str, value: str) -> dict:
    return {"from_name": name, "to_name": "image", "type": "textarea", "value": {"text": [value]}}


def choice_value(name: str, value: str) -> dict:
    return {"from_name": name, "to_name": "image", "type": "choices", "value": {"choices": [value]}}


def tasks(ls: LS, pid: int) -> list[dict]:
    out, page = [], 1
    while True:
        r = ls("GET", "/api/tasks", params={"project": pid, "page": page, "page_size": 100, "fields": "all"})
        out += r["tasks"]
        if len(out) >= r["total"]:
            return out
        page += 1


def push() -> None:
    ls = LS()
    p = project(ls)
    have = {t["data"]["file"] for t in tasks(ls, p["id"])}
    synthetic = {m["file"]: m for m in json.loads((evalenv.DATA / "synthetic.json").read_text(encoding="utf-8"))}
    added = 0
    for path in sorted(evalenv.PHOTOS.rglob("*")):
        rel = path.relative_to(evalenv.PHOTOS).as_posix()
        if path.suffix.lower() not in EXTS or rel in have:
            continue
        task = {"data": {"image": f"/data/local-files/?d=ocr/{rel}", "file": rel}}
        m = synthetic.get(rel)
        if m:
            result = [text_value("page_id", m["page_id"]), text_value("page_text", m["truth"])]
            if m["page_number"] is not None:
                result.append(text_value("page_number", str(m["page_number"])))
            result += [choice_value(k, m[k]) for k in TAGS]
            task["annotations"] = [{"result": result}]
        ls("POST", f"/api/projects/{p['id']}/import", json=[task])
        added += 1
    print(f"project {p['id']} '{TITLE}': {added} task(s) added, {len(have) + added} in all; "
          f"open {evalenv.LABEL_STUDIO_URL}/projects/{p['id']}")


def pull() -> None:
    ls = LS()
    p = project(ls)
    rows = {}
    for t in tasks(ls, p["id"]):
        anns = [a for a in t.get("annotations") or [] if not a.get("was_cancelled")]
        if not anns:
            continue
        ann = max(anns, key=lambda a: a.get("updated_at") or "")
        row = {"file": t["data"]["file"]}
        for r in ann["result"]:
            v = r["value"]
            if r["from_name"] in ("page_id", "page_text", "page_number") and "text" in v:
                row[r["from_name"]] = "\n".join(v["text"]).strip()
            elif r["from_name"] in TAGS and v.get("choices"):
                row[r["from_name"]] = v["choices"][0]
        rows[row["file"]] = row
    # Typed once per page: a photo with only the page id takes the text from another photo of that page.
    by_page = {r["page_id"]: r for r in rows.values() if r.get("page_id") and r.get("page_text")}
    for r in rows.values():
        src = by_page.get(r.get("page_id", ""))
        if src and not r.get("page_text"):
            r["page_text"] = src["page_text"]
            r.setdefault("page_number", src.get("page_number", ""))
    evalenv.TRUTH.write_text(json.dumps(sorted(rows.values(), key=lambda r: r["file"]), indent=1,
                                        ensure_ascii=False), encoding="utf-8")
    done = sum(1 for r in rows.values() if r.get("page_text"))
    print(f"{len(rows)} annotated photo(s), {done} with page text → {evalenv.TRUTH}")


if __name__ == "__main__":
    {"push": push, "pull": pull}[sys.argv[1]]()
