"""OCR evaluation run (trial): Leafi's page OCR on every photo, scored with jiwer, logged to every tool.

    .venv-eval\\Scripts\\python scripts/evals/ocr/run.py --pipeline default
    .venv-eval\\Scripts\\python scripts/evals/ocr/run.py --pipeline probe-k2 [--source synthetic] [--sinks mlflow,phoenix]

What one run does:
1. Reads cache/evals/ocr/truth.json (from `labels.py pull`) and every photo under cache/evals/ocr/photos/.
2. Runs `RapidOcr` (`purpose="page"`) with the named pipeline's parameters, carrying the remembered angle from
   one photo to the next as the live reader does. Each internal step is an OpenTelemetry span
   (read → remembered pass → probe → probe/scan passes → choose → page number → missing-words guard → score).
3. Scores the page text against the truth with jiwer: CER and WER, raw (line breaks as spaces) and normalised
   (lower case, no punctuation), per photo, overall and per condition tag.
4. Sends the same spans to MLflow, Phoenix and Langfuse (OTLP), and logs the run itself to each tool's own
   experiment model (MLflow run, Phoenix experiment, Langfuse dataset run), and to FiftyOne per photo.

Everything goes to this PC only (`evalenv.local` refuses anything else). Prints numbers, never page text.
Leafi is imported without `leafi/__init__.py`: that file aliases httpx to httpx2 for the project venv, and the
tools here need the real httpx.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import time
import types
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evalenv  # noqa: E402  (telemetry off, before any tool is imported)

sys.path.insert(0, str(evalenv.REPO))
_pkg = types.ModuleType("leafi")
_pkg.__path__ = [str(evalenv.REPO / "leafi")]
sys.modules["leafi"] = _pkg

import fiftyone as fo  # noqa: E402  (before mlflow: voxel51-eta breaks once mlflow loads importlib_metadata)
import jiwer  # noqa: E402
import mlflow  # noqa: E402
import requests  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: E402
from PIL import Image  # noqa: E402

import leafi.services.ocr.rapidocr as rapid  # noqa: E402
from leafi.study.page_tracker import is_partial, missing_words, split_number  # noqa: E402

TAG_KEYS = (*evalenv.tags(), "source")
EXTS = {".jpg", ".jpeg", ".png"}
EXPERIMENT = "leafi-ocr"

# A pipeline = the stage-1 reader plus named settings. `structure` changes which steps run, not just values.
PIPELINES = {
    "default": {"rotations": "270,90,0", "probe_k": 6, "min_conf": 0.85, "structure": "remembered+probe+scan"},
    "probe-k2": {"rotations": "270,90,0", "probe_k": 2, "min_conf": 0.85, "structure": "remembered+probe+scan"},
    "scan-only": {"rotations": "270,90,0", "probe_k": 6, "min_conf": 0.85, "structure": "scan"},
}
PIPELINE_VERSION = "ocr-stage1"  # design 2026-10-25 rev 7, commit ed983c0

NORM = jiwer.Compose([jiwer.ToLowerCase(), jiwer.RemovePunctuation(), jiwer.RemoveMultipleSpaces(), jiwer.Strip()])


def flat(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------- tracing
def tracer_provider(sinks: set[str], run_name: str, mlflow_experiment_id: str | None,
                    lf_experiment: LangfuseExperiment) -> TracerProvider:
    """One provider, one exporter per tool: every tool receives the same spans."""
    resource = Resource.create({"service.name": "leafi-ocr-eval", "openinference.project.name": EXPERIMENT,
                                "leafi.run": run_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(lf_experiment)  # adds attributes only; the other tools ignore them
    if "phoenix" in sinks:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=evalenv.local(evalenv.PHOENIX_URL) + "/v1/traces")))
    if "langfuse" in sinks:
        s = evalenv.secrets()
        auth = base64.b64encode(f"{s['LANGFUSE_PUBLIC_KEY']}:{s['LANGFUSE_SECRET_KEY']}".encode()).decode()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=evalenv.local(evalenv.LANGFUSE_URL) + "/api/public/otel/v1/traces",
            headers={"Authorization": "Basic " + auth})))
    if "mlflow" in sinks and mlflow_experiment_id:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=evalenv.local(evalenv.MLFLOW_URI) + "/v1/traces",
            headers={"x-mlflow-experiment-id": mlflow_experiment_id})))
    return provider


class LangfuseExperiment(SpanProcessor):
    """Langfuse v4 ("events only") knows a dataset run only from `langfuse.experiment.*` attributes on every span
    of the item's trace (what the SDK's `run_experiment` propagates); the old dataset-run-items REST call is
    accepted but not shown. `item` is set per photo by the runner; None leaves the trace outside the experiment."""

    def __init__(self) -> None:
        self.item: dict | None = None
        self.root: str | None = None

    def on_start(self, span, parent_context=None) -> None:
        if not self.item:
            return
        if self.root is None:
            self.root = format(span.get_span_context().span_id, "016x")
        span.set_attributes({**self.item, "langfuse.experiment.item.root_observation_id": self.root,
                             "langfuse.environment": "sdk-experiment"})

    def begin(self, item: dict | None) -> None:
        self.item, self.root = item, None


class Traced(rapid.RapidOcr):
    """RapidOcr with a span around each internal step; the decisions themselves are the unchanged parent's."""

    tracer: trace.Tracer

    def _pass(self, img, angle, kind):
        with self.tracer.start_as_current_span(f"pass.{kind}") as s:
            p = super()._pass(img, angle, kind)
            s.set_attributes({"openinference.span.kind": "CHAIN", "ocr.angle": angle, "ocr.kind": kind,
                              "ocr.score": round(p.score, 1), "ocr.lines.wide": sum(1 for ln in p.lines if ln.wide),
                              "ocr.lines.total": len(p.lines), "ocr.lines.body": len(p.body),
                              "ocr.evident": rapid.evident(p, self.min_conf), "ocr.seconds": round(p.seconds, 3)})
            return p

    def _probe(self, img):
        with self.tracer.start_as_current_span("probe") as s:
            nominee, scores, secs = super()._probe(img)
            s.set_attributes({"openinference.span.kind": "CHAIN", "ocr.probe_k": rapid.PROBE_K,
                              "ocr.nominee": -1 if nominee is None else nominee, "ocr.seconds": round(secs, 3),
                              **{f"ocr.probe_score.{a}": round(v, 1) for a, v in scores.items()}})
            return nominee, scores, secs

    def _choose(self, tried, probe, score=lambda p: p.score):
        with self.tracer.start_as_current_span("choose") as s:
            best, state = super()._choose(tried, probe, score)
            s.set_attributes({"openinference.span.kind": "CHAIN", "ocr.angle": best.angle, "ocr.state": state,
                              "ocr.candidates": len(tried)})
            return best, state


class ScanOnly(Traced):
    """Structural variant: no probe; every listed angle is read and the best is chosen."""

    def _probe(self, img):
        return None, {}, 0.0


# ---------------------------------------------------------------- data
@dataclass
class Photo:
    file: str
    path: Path
    truth: str | None = None
    page_number: int | None = None
    tags: dict = field(default_factory=dict)
    page_id: str = ""

    @property
    def tag_list(self) -> list[str]:
        return [f"{k}:{v}" for k, v in self.tags.items() if v]


def photos(source: str) -> list[Photo]:
    truth = {r["file"]: r for r in json.loads(evalenv.TRUTH.read_text(encoding="utf-8"))} \
        if evalenv.TRUTH.exists() else {}
    out = []
    for path in sorted(evalenv.PHOTOS.rglob("*")):
        rel = path.relative_to(evalenv.PHOTOS).as_posix()
        if path.suffix.lower() not in EXTS:
            continue
        src = "synthetic" if rel.startswith("synthetic/") else "camera"
        if source not in ("all", src):
            continue
        r = truth.get(rel, {})
        num = (r.get("page_number") or "").strip()
        out.append(Photo(rel, path, r.get("page_text") or None, int(num) if num.isdigit() else None,
                         {**{k: r.get(k, "") for k in TAG_KEYS[:-1]}, "source": src}, r.get("page_id", "")))
    return out


def thumbnail_uri(path: Path, width: int = 960) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((width, width))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- scoring
def score(truth: str, pred: str) -> dict:
    ref, hyp = flat(truth), flat(pred)
    out = {}
    for kind, r, h in (("raw", ref, hyp), ("norm", NORM(ref), NORM(hyp))):
        c = jiwer.process_characters(r, h)
        w = jiwer.process_words(r, h)
        out[f"cer_{kind}"], out[f"wer_{kind}"] = round(c.cer, 4), round(w.wer, 4)
        if kind == "norm":
            out["align_words"] = jiwer.visualize_alignment(w, show_measures=False, skip_correct=False)
            out["ref_chars"] = sum(len(x) for x in r)
            out["char_edits"] = c.substitutions + c.deletions + c.insertions
            out["ref_words"] = len(r.split())
            out["word_edits"] = w.substitutions + w.deletions + w.insertions
    return out


def aggregate(rows: list[dict]) -> dict:
    """Corpus CER/WER (edits ÷ reference length) overall and per tag value, over photos with truth."""
    scored = [r for r in rows if r.get("cer_norm") is not None]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        groups["all"].append(r)
        for t in r["tags"]:
            groups[t].append(r)
    out = {}
    for g, rs in groups.items():
        key = g.replace(":", "_").replace(" ", "_")
        out[f"cer_norm.{key}"] = round(sum(r["char_edits"] for r in rs) / max(1, sum(r["ref_chars"] for r in rs)), 4)
        out[f"wer_norm.{key}"] = round(sum(r["word_edits"] for r in rs) / max(1, sum(r["ref_words"] for r in rs)), 4)
        out[f"n.{key}"] = len(rs)
    if scored:
        out["cer_raw.mean"] = round(sum(r["cer_raw"] for r in scored) / len(scored), 4)
        out["wer_raw.mean"] = round(sum(r["wer_raw"] for r in scored) / len(scored), 4)
        rot = [r for r in scored if r["expected_rotation"] is not None]
        if rot:
            out["rotation_accuracy"] = round(sum(r["rotation"] == r["expected_rotation"] for r in rot) / len(rot), 4)
        num = [r for r in scored if r["truth_number"] is not None]
        if num:
            out["page_number_accuracy"] = round(sum(r["page_number"] == r["truth_number"] for r in num) / len(num), 4)
    out["seconds.mean"] = round(sum(r["seconds"] for r in rows) / max(1, len(rows)), 3)
    out["passes.mean"] = round(sum(r["passes"] for r in rows) / max(1, len(rows)), 3)
    out["state_sure.share"] = round(sum(r["state"] == "sure" for r in rows) / max(1, len(rows)), 4)
    return out


# ---------------------------------------------------------------- the run
def run_ocr(ocr: Traced, tracer, items: list[Photo], run_name: str, cfg: dict, meta: dict, images: bool,
            lf_experiment: LangfuseExperiment, lf_items: dict[str, dict]) -> list[dict]:
    rows = []
    angle, region = None, None
    for ph in items:
        expected = {"0": 0, "90": 90, "180": 180, "270": 270}.get(ph.tags.get("angle", ""))
        lf_experiment.begin(lf_items.get(ph.file))
        with tracer.start_as_current_span("ocr.page") as root:
            root.set_attributes({
                "openinference.span.kind": "CHAIN", "session.id": run_name, "langfuse.trace.name": "ocr.page",
                "langfuse.trace.tags": [meta["pipeline"], *ph.tag_list],
                "eval.run": run_name, "eval.file": ph.file, "eval.page_id": ph.page_id,
                **{f"langfuse.trace.metadata.{k}": str(v) for k, v in meta.items()},
                **{f"eval.tag.{k}": v for k, v in ph.tags.items() if v},
                **{f"eval.{k}": str(v) for k, v in meta.items()},
            })
            if images:
                uri = thumbnail_uri(ph.path)
                root.set_attribute("input.value", json.dumps({"file": ph.file, "image": uri}))
                root.set_attribute("input.mime_type", "application/json")
                # OpenInference image message: how Phoenix shows a picture in a span (checked in the trial)
                root.set_attribute("llm.input_messages.0.message.role", "user")
                root.set_attribute("llm.input_messages.0.message.contents.0.message_content.type", "image")
                root.set_attribute("llm.input_messages.0.message.contents.0.message_content.image.image.url", uri)
            else:
                root.set_attribute("input.value", ph.file)
            t0 = time.perf_counter()
            with tracer.start_as_current_span("read") as s:
                data = ph.path.read_bytes()
                s.set_attributes({"openinference.span.kind": "CHAIN", "image.bytes": len(data)})
            mem_angle = angle if cfg["structure"] != "scan" else None
            with tracer.start_as_current_span("ocr.read") as s:
                res = ocr._read(data, "page", mem_angle, region)
                s.set_attributes({"openinference.span.kind": "CHAIN", "ocr.rotation": res.rotation,
                                  "ocr.state": res.state, "ocr.passes": len(res.passes),
                                  "ocr.remembered": -1 if mem_angle is None else mem_angle})
            if res.state == "sure":  # what `RapidOcr._run` publishes for the next read
                angle, region = res.rotation, res.region
            with tracer.start_as_current_span("page_number") as s:
                number, body = split_number(res.lines, ocr.min_conf)
                s.set_attributes({"openinference.span.kind": "CHAIN", "page.number": -1 if number is None else number,
                                  "page.number.truth": -1 if ph.page_number is None else ph.page_number})
            text = "\n".join(body)
            seconds = time.perf_counter() - t0
            row = {"file": ph.file, "tags": ph.tag_list, "tag_map": ph.tags, "page_id": ph.page_id, "text": text,
                   "rotation": res.rotation, "expected_rotation": expected, "state": res.state,
                   "passes": len(res.passes), "seconds": round(seconds, 3), "page_number": number,
                   "truth_number": ph.page_number, "truth": ph.truth,
                   "trace_id": format(root.get_span_context().trace_id, "032x"),
                   "cer_norm": None}
            with tracer.start_as_current_span("missing_words_guard") as s:
                if ph.truth:
                    missing, total = missing_words(ph.truth, text)
                    row["guard_partial"] = is_partial(ph.truth, text)
                    s.set_attributes({"openinference.span.kind": "CHAIN", "guard.missing": missing,
                                      "guard.total": total, "guard.partial": row["guard_partial"]})
                else:
                    s.set_attribute("guard.skipped", "no truth")
            if ph.truth:
                with tracer.start_as_current_span("score") as s:
                    row.update(score(ph.truth, text))
                    s.set_attributes({"openinference.span.kind": "EVALUATOR",
                                      **{k: row[k] for k in ("cer_raw", "cer_norm", "wer_raw", "wer_norm")}})
            root.set_attributes({"output.value": text, "ocr.rotation": res.rotation, "ocr.state": res.state,
                                 "langfuse.trace.output": text,
                                 **({"eval.cer_norm": row["cer_norm"]} if ph.truth else {})})
        rows.append(row)
        print(f"  {ph.file:<44} rot {res.rotation:>3} {res.state:<8} passes {len(res.passes)} "
              f"{seconds:5.1f}s" + (f"  CER {row['cer_norm']:.3f} WER {row['wer_norm']:.3f}" if ph.truth else
                                    "  (no truth yet)"))
    lf_experiment.begin(None)
    return rows


# ---------------------------------------------------------------- sinks
def to_fiftyone(rows: list[dict], items: list[Photo], key: str, meta: dict, metrics: dict) -> None:
    ds = fo.load_dataset(evalenv.DATASET) if fo.dataset_exists(evalenv.DATASET) else \
        fo.Dataset(evalenv.DATASET, persistent=True)
    by_path = {s.filepath: s for s in ds}
    new = []
    for ph in items:
        if str(ph.path) not in by_path:
            new.append(fo.Sample(filepath=str(ph.path)))
    if new:
        ds.add_samples(new)
        by_path = {s.filepath: s for s in ds}
    # Declared up front: FiftyOne cannot infer a field's type from a first value of None (no truth yet).
    kinds = {"file": fo.StringField, "page_id": fo.StringField, "truth": fo.StringField,
             "truth_page_number": fo.IntField, f"{key}_text": fo.StringField, f"{key}_rotation": fo.IntField,
             f"{key}_state": fo.StringField, f"{key}_page_number": fo.IntField, f"{key}_cer": fo.FloatField,
             f"{key}_wer": fo.FloatField, f"{key}_cer_raw": fo.FloatField, f"{key}_alignment": fo.StringField,
             f"{key}_trace_id": fo.StringField}
    have = ds.get_field_schema()
    for name, kind in kinds.items():
        if name not in have:
            ds.add_sample_field(name, kind)
    rows_by = {r["file"]: r for r in rows}
    for ph in items:
        s = by_path[str(ph.path)]
        r = rows_by[ph.file]
        s.tags = sorted(set(t for t in s.tags if ":" not in t) | set(ph.tag_list))
        s["file"], s["page_id"], s["truth"], s["truth_page_number"] = ph.file, ph.page_id, ph.truth, ph.page_number
        s[f"{key}_text"] = r["text"]
        s[f"{key}_rotation"] = r["rotation"]
        s[f"{key}_state"] = r["state"]
        s[f"{key}_page_number"] = r["page_number"]
        s[f"{key}_cer"] = r.get("cer_norm")
        s[f"{key}_wer"] = r.get("wer_norm")
        s[f"{key}_cer_raw"] = r.get("cer_raw")
        s[f"{key}_alignment"] = r.get("align_words")
        s[f"{key}_trace_id"] = r["trace_id"]
        s.save()
    info = dict(ds.info or {})
    info.setdefault("runs", {})[key] = {**meta, "metrics": {k: v for k, v in metrics.items() if "." not in k or k.endswith(".all")}}
    ds.info = info
    ds.save()
    print(f"FiftyOne: dataset '{evalenv.DATASET}', fields {key}_*; {len(items)} samples")


def to_mlflow(rows, metrics, meta, cfg, run_name, out_dir: Path, exp_id: str) -> None:
    with mlflow.start_run(experiment_id=exp_id, run_name=run_name) as run:
        mlflow.set_tags({"git_commit": meta["git_commit"], "git_dirty": str(meta["git_dirty"]),
                         "pipeline": meta["pipeline"], "pipeline_version": meta["pipeline_version"]})
        mlflow.log_params({**cfg, "pipeline": meta["pipeline"], "ocr_version": rapid.DEFAULT_VERSION,
                           "photos": len(rows), "memory": "carried in file order"})
        mlflow.log_metrics({k.replace(":", "_"): v for k, v in metrics.items()})
        table = [{k: r.get(k) for k in ("file", "page_id", "rotation", "expected_rotation", "state", "passes",
                                         "seconds", "page_number", "truth_number", "cer_norm", "wer_norm",
                                         "cer_raw", "wer_raw", "guard_partial", "trace_id")} |
                 {"tags": " ".join(r["tags"])} for r in rows]
        mlflow.log_table({k: [t[k] for t in table] for k in table[0]}, "per_photo.json")
        mlflow.log_artifacts(str(out_dir), "run")
        ids = ["tr-" + r["trace_id"] for r in rows]
        try:
            mlflow.MlflowClient().link_traces_to_run(ids, run.info.run_id)
            for r in rows:
                if r.get("cer_norm") is not None:
                    mlflow.log_feedback(trace_id="tr-" + r["trace_id"], name="cer_norm", value=r["cer_norm"])
        except Exception as e:  # traces may still be ingesting; the run itself is complete
            print(f"MLflow: traces not linked ({type(e).__name__}: {e})")
        print(f"MLflow: run '{run_name}' {evalenv.MLFLOW_URI}/#/experiments/{exp_id}/runs/{run.info.run_id}")


def to_phoenix(rows, metrics, meta, run_name) -> None:
    from phoenix.client import Client

    client = Client(base_url=evalenv.local(evalenv.PHOENIX_URL))
    scored = [r for r in rows if r.get("cer_norm") is not None]
    if not scored:
        print("Phoenix: no photo with truth; experiment skipped")
        return
    name = EXPERIMENT
    try:
        ds = client.datasets.get_dataset(dataset=name)
        have = {ex["input"]["file"] for ex in ds.examples}
        missing = [r for r in scored if r["file"] not in have]
        if missing:
            ds = client.datasets.add_examples_to_dataset(
                dataset=name, inputs=[{"file": r["file"]} for r in missing],
                outputs=[{"text": r["truth"]} for r in missing],
                metadata=[{**r["tag_map"], "page_id": r["page_id"]} for r in missing])
    except Exception:
        ds = client.datasets.create_dataset(
            name=name, inputs=[{"file": r["file"]} for r in scored], outputs=[{"text": r["truth"]} for r in scored],
            metadata=[{**r["tag_map"], "page_id": r["page_id"]} for r in scored],
            dataset_description="Leafi page photos with typed page text")
    by_file = {r["file"]: r for r in rows}

    def task(input):  # the OCR already ran (and was traced) above; the experiment records its output
        r = by_file.get(input["file"])
        return {"text": r["text"] if r else "", "rotation": r["rotation"] if r else None}

    def cer(output, expected):
        return score(expected["text"], output["text"])["cer_norm"]

    def wer(output, expected):
        return score(expected["text"], output["text"])["wer_norm"]

    client.experiments.run_experiment(dataset=ds, task=task, evaluators={"cer_norm": cer, "wer_norm": wer},
                                      experiment_name=run_name, experiment_metadata={**meta, **{
                                          k: v for k, v in metrics.items() if k.endswith(".all")}},
                                      print_summary=False)
    print(f"Phoenix: experiment '{run_name}' on dataset '{name}'; traces in project '{EXPERIMENT}' "
          f"({evalenv.PHOENIX_URL})")


def langfuse_call(method, path, **kw):
    s = evalenv.secrets()
    r = requests.request(method, evalenv.local(evalenv.LANGFUSE_URL) + "/api/public" + path,
                         auth=(s["LANGFUSE_PUBLIC_KEY"], s["LANGFUSE_SECRET_KEY"]), timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def langfuse_prepare(items: list[Photo], run_name: str, meta: dict) -> dict[str, dict]:
    """Dataset and items before the run (upserted by id); returns each scored photo's experiment attributes."""
    name = EXPERIMENT
    try:
        ds = langfuse_call("GET", f"/v2/datasets/{name}")
    except requests.HTTPError:
        ds = langfuse_call("POST", "/v2/datasets",
                           json={"name": name, "description": "Leafi page photos with typed page text"})
    experiment_id = hashlib.sha256(run_name.encode()).hexdigest()[:32]
    out = {}
    for ph in items:
        if not ph.truth:
            continue
        item_id = ph.file.replace("/", "__")
        metadata = {**ph.tags, "page_id": ph.page_id}
        langfuse_call("POST", "/dataset-items", json={"datasetName": name, "id": item_id, "input": {"file": ph.file},
                                                      "expectedOutput": {"text": ph.truth}, "metadata": metadata})
        out[ph.file] = {
            "langfuse.experiment.id": experiment_id, "langfuse.experiment.name": run_name,
            "langfuse.experiment.description": f"{meta['pipeline']} @ {meta['git_commit'][:7]}",
            "langfuse.experiment.metadata": json.dumps({k: str(v) for k, v in meta.items()}),
            "langfuse.experiment.dataset.id": ds["id"], "langfuse.experiment.item.id": item_id,
            "langfuse.experiment.item.expected_output": json.dumps({"text": ph.truth}),
            "langfuse.experiment.item.metadata": json.dumps(metadata),
        }
    return out


def to_langfuse(rows, run_name, lf_items: dict[str, dict]) -> None:
    """Scores on each trace (the experiment itself travels in the span attributes)."""
    for r in rows:
        for k in ("cer_norm", "wer_norm", "cer_raw"):
            if r.get(k) is not None:
                langfuse_call("POST", "/scores", json={"traceId": r["trace_id"], "name": k, "value": r[k],
                                                       "dataType": "NUMERIC"})
        if r["expected_rotation"] is not None:
            langfuse_call("POST", "/scores", json={"traceId": r["trace_id"], "name": "rotation_ok",
                                                   "value": float(r["rotation"] == r["expected_rotation"]),
                                                   "dataType": "NUMERIC"})
    print(f"Langfuse: experiment '{run_name}' on dataset '{EXPERIMENT}' ({len(lf_items)} item(s)); "
          f"{evalenv.LANGFUSE_URL}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", choices=sorted(PIPELINES), default="default")
    ap.add_argument("--source", choices=("all", "synthetic", "camera"), default="all")
    ap.add_argument("--sinks", default="fiftyone,mlflow,phoenix,langfuse")
    ap.add_argument("--no-images", action="store_true", help="keep photos out of the traces")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--run-name", help="reuse a run's name, e.g. to send it again to one tool with --sinks")
    args = ap.parse_args()
    sinks = set(args.sinks.split(","))
    cfg = PIPELINES[args.pipeline]
    commit, dirty = evalenv.git_state()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_name = args.run_name or f"{args.pipeline}-{stamp}"
    meta = {"pipeline": args.pipeline, "pipeline_version": PIPELINE_VERSION, "git_commit": commit,
            "git_dirty": dirty, "source": args.source, "run": run_name}
    items = photos(args.source)[: args.limit]

    exp_id = None
    if "mlflow" in sinks:
        mlflow.set_tracking_uri(evalenv.local(evalenv.MLFLOW_URI))
        exp = mlflow.get_experiment_by_name(EXPERIMENT)
        exp_id = exp.experiment_id if exp else mlflow.create_experiment(EXPERIMENT)
    lf_experiment = LangfuseExperiment()
    lf_items = langfuse_prepare(items, run_name, meta) if "langfuse" in sinks else {}
    provider = tracer_provider(sinks, run_name, exp_id, lf_experiment)
    tracer = provider.get_tracer("leafi.ocr.eval")

    rapid.PROBE_K = cfg["probe_k"]
    settings = types.SimpleNamespace(ocr_version=rapid.DEFAULT_VERSION, ocr_min_confidence=cfg["min_conf"],
                                     ocr_rotations=cfg["rotations"])
    ocr = (ScanOnly if cfg["structure"] == "scan" else Traced)(settings)
    ocr.tracer = tracer
    for stage in ("full", "det", "rec"):  # model load outside the timed spans
        ocr._engine(stage)

    print(f"run {run_name}: {len(items)} photo(s), pipeline {args.pipeline} {cfg}, commit {commit[:7]}"
          + (" (dirty)" if dirty else ""))
    rows = run_ocr(ocr, tracer, items, run_name, cfg, meta, not args.no_images, lf_experiment, lf_items)
    provider.force_flush()
    metrics = aggregate(rows)

    out_dir = evalenv.DATA / "runs" / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rows.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps({"meta": meta, "params": cfg, "metrics": metrics}, indent=1),
                                          encoding="utf-8")
    (out_dir / "alignments.txt").write_text("\n\n".join(f"== {r['file']}\n{r['align_words']}" for r in rows
                                                        if r.get("align_words")), encoding="utf-8")
    key = "ocr_" + args.pipeline.replace("-", "_")
    if "fiftyone" in sinks:
        to_fiftyone(rows, items, key, meta, metrics)
    if "mlflow" in sinks:
        to_mlflow(rows, metrics, meta, cfg, run_name, out_dir, exp_id)
    if "phoenix" in sinks:
        to_phoenix(rows, metrics, meta, run_name)
    if "langfuse" in sinks:
        to_langfuse(rows, run_name, lf_items)
    provider.shutdown()
    print("metrics:", json.dumps({k: v for k, v in metrics.items() if not k.startswith("n.")}, sort_keys=True))


if __name__ == "__main__":
    main()
