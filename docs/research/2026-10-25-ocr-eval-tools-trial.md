# OCR evaluation tools: a local trial of MLflow, Phoenix and Langfuse (with FiftyOne, jiwer, Label Studio)

Checked: 2026-10-25. A prototype, not an adoption: using any of these tools inside `leafi/` is a design change
(research → design → review, `AGENTS.md`). Code: `scripts/evals/ocr/`. Data, secrets and logs: the main checkout's
gitignored `cache/evals/`. Tiers: T1 = measured here or read in the installed package; T2 = vendor docs.

**中文一句话总结：** 三个工具都能在本机关掉遥测后跑通 OCR 评测；比较参数和看分标签结果首选 MLflow，看单张照片的步骤和图片首选 Langfuse，Phoenix 介于两者之间；推荐以 MLflow + FiftyOne 为主，Langfuse 留给以后的 LLM 开发。

## 1. What was built

| Piece | Tool | Where | Host port |
|---|---|---|---|
| Photo dataset, tags, per-run predictions | FiftyOne 1.22.1 (pip) | `.venv-eval`, `fo_app.py` | 19151 |
| Ground truth typing | Label Studio 1.23.2 (container) | `labels.py push / pull` | 19080 |
| CER / WER and alignments | jiwer 4.0.0 | `run.py` | — |
| Runs, parameters, metrics, traces | MLflow 3.17.2 (pip, SQLite) | `stack.ps1 mlflow` | 19500 |
| Traces, datasets, experiments | Phoenix 20.26.1 (container) | `docker-compose.yml` | 19006 |
| Traces, datasets, dataset runs, scores | Langfuse 4.70.0 (Docker Compose: web, worker, Postgres, ClickHouse, Redis, MinIO) | `docker-compose.yml` | 19300 (MinIO 19090) |

Versions are the latest releases on 2026-10-25 (PyPI and GitHub releases checked that day). `.venv-eval` is a
separate uv venv (Python 3.12); the project `.venv` is untouched.

Commands (PowerShell, from the repository root):

```
scripts\evals\ocr\stack.ps1 up            # containers; first run writes cache\evals\stack.env with fresh secrets
scripts\evals\ocr\stack.ps1 mlflow        # MLflow server
scripts\evals\ocr\stack.ps1 fiftyone      # FiftyOne app
.venv-eval\Scripts\python scripts/evals/ocr/make_synthetic.py   # 12 synthetic photos
.venv-eval\Scripts\python scripts/evals/ocr/labels.py push      # tasks in Label Studio
.venv-eval\Scripts\python scripts/evals/ocr/labels.py pull      # annotations -> truth.json
.venv-eval\Scripts\python scripts/evals/ocr/run.py --pipeline default    # also probe-k2, scan-only
scripts\evals\ocr\netwatch.ps1 -Seconds 300 [-Control]          # egress proof
```

(`.venv-eval` lives in the main checkout; from a worktree use its full path.)

### 1.1 The run

`run.py` runs `RapidOcr` (`purpose="page"`) on every photo with a named pipeline, carrying the remembered angle
from photo to photo like the live reader. A subclass wraps `_pass`, `_probe` and `_choose` in OpenTelemetry spans
without changing a decision. One trace per photo:

```
ocr.page (file, tags, run, git commit, dirty, pipeline, thumbnail)
├─ read                      image bytes
├─ ocr.read                  rotation, state, passes, remembered angle
│  ├─ pass.remembered        angle, score, wide/total/body lines, evident
│  ├─ probe                  probe_k, nominee, score per angle
│  ├─ pass.probe / pass.scan angle, score, lines
│  └─ choose                 angle, state, candidates
├─ page_number               predicted vs typed number (split_number)
├─ missing_words_guard       missing, total, partial (is_partial against the truth)
└─ score                     CER/WER raw and normalised
```

One `TracerProvider` with three OTLP exporters sends the same spans to MLflow (`/v1/traces`), Phoenix
(`/v1/traces`) and Langfuse (`/api/public/otel/v1/traces`). The run itself is also logged in each tool's own
model: an MLflow run (params, metrics, per-photo table, artifacts, traces linked, CER feedback on each trace), a
Phoenix experiment on a Phoenix dataset, a Langfuse dataset run with scores on each trace. FiftyOne gets
`ocr_<pipeline>_text / _cer / _wer / _rotation / _state / _page_number / _alignment / _trace_id` per photo.

Scores: CER and WER from jiwer, *raw* (line breaks as spaces) and *normalised* (lower case, no punctuation,
single spaces); per photo, overall, and per tag value as corpus rates (edits ÷ reference length).

### 1.2 Pipelines compared

| Name | What differs | Kind |
|---|---|---|
| `default` | `OCR_ROTATIONS=270,90,0`, `PROBE_K=6`, remembered angle + probe + scan | stage 1 as merged |
| `probe-k2` | `PROBE_K=2` | one parameter |
| `scan-only` | no probe, no remembered angle: every listed angle is read | structure |

### 1.3 Dataset

21 photos: 9 camera photos already on disk (`cache/checks`, `cache/desk`, `cache/pages`; copied, never opened by
the agent) and 12 synthetic ones from `make_synthetic.py`. The real photos show the home and a child, and the
agent here is a cloud model, so it neither looked at them nor printed their OCR text; their ground truth and
tags are for the owner to type in Label Studio. The synthetic photos copy the wide shot (1920×1080, page about a
fifth of the frame, capitals about 15 px, the camera clock) and carry every tag, with text written for the
generator, so the whole workflow could be checked before real truth exists.

Tags (one Label Studio choice each; `angle:270` style in FiftyOne): angle 0/90/180/270/tilted, hand
none/edge/covering, desk clean/cluttered, light normal/dim/glare, layout plain/decorative font/text around
picture/spread, plus source synthetic/camera. Ground truth is typed once per page id; other photos of the page
give only the page id (`labels.py pull` fills them in).

## 2. Telemetry off, and the proof

| Tool | Switch set | Where |
|---|---|---|
| MLflow | `MLFLOW_DISABLE_TELEMETRY=true`, `DO_NOT_TRACK=true` | `evalenv.py`, `stack.ps1` |
| FiftyOne | `FIFTYONE_DO_NOT_TRACK=true` | same |
| Phoenix | `PHOENIX_TELEMETRY_ENABLED=false` | container env (and client env) |
| Langfuse | `TELEMETRY_ENABLED=false`, `NEXT_TELEMETRY_DISABLED=1` | web and worker env |
| Label Studio | `COLLECT_ANALYTICS=false`, `LATEST_VERSION_CHECK=false`, `CONVERTER_DOWNLOAD_RESOURCES=false`, empty Sentry DSNs | container env |
| MinIO | `MINIO_UPDATE=off` | container env |

Switches are a promise; the proof is the network:

1. **Containers cannot reach the internet at all.** Every tool container is only on `tools`, a Docker network
   with `internal: true`. One nginx container (`gate`) sits on both networks and forwards the published
   127.0.0.1 ports inward. `netwatch.ps1` joins a throwaway busybox to each container's own network namespace and
   tries TCP 1.1.1.1:443: all nine tool containers `BLOCKED`; the gate (control) `REACHED`, so the test can
   succeed (T1, 2026-10-25 14:35).
2. **Host processes** (the `.venv-eval` Python of MLflow, FiftyOne, the runner, and FiftyOne's `mongod`):
   `netwatch.ps1` polls the TCP table every second and logs every non-loopback remote address. A venv's
   `python.exe` is a launcher whose child (the base Python) does the work, so the watch follows the process
   tree; its first version matched command lines and missed the control. Control: a `.venv-eval` Python that
   opens TCP 1.1.1.1:443 for 4 s is caught (`OUTBOUND ... 1.1.1.1:443`). Result over the trial: see §5.
3. **The browser** (outside the internal network): each UI's resource list was read in the page. MLflow and
   Label Studio stay local; Phoenix did not until `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false`; FiftyOne (Google
   Fonts) and Langfuse (a shields.io badge) still do. See §5.
4. **Endpoints cannot fall back to a cloud.** The Langfuse SDK defaults to `https://cloud.langfuse.com` when no
   base URL is set; `evalenv.local()` refuses any endpoint that is not 127.0.0.1/localhost, and the runner talks
   to Langfuse by plain REST plus OTLP with explicit URLs.

No LLM-as-judge is used anywhere: every score is jiwer arithmetic.

## 3. Results of the trial runs (synthetic photos, T1)

| Run | CER norm (all) | WER norm (all) | Rotation correct | Page number correct | Passes / photo | s / photo |
|---|---|---|---|---|---|---|
| `default-20261025-152215` | 0.163 | 0.188 | 12/12 | 5/11 | 1.90 | 3.37 |
| `probe-k2-20261025-152605` | 0.163 | 0.188 | 12/12 | 5/11 | 2.19 | 3.42 |
| `scan-only-20261025-152958` | 0.163 | 0.188 | 12/12 | 5/11 | 3.00 | 3.92 |

These three (commit `b184079`, clean) are the runs to compare in every tool; passes and seconds are over all 21
photos. Earlier runs in the tools (14:42–14:52, and `lf-v4-check`) are set-up attempts. The three were sent to
Langfuse a second time under the same names after the v4 fix (§4.4), which also rewrote their local
`cache/evals/ocr/runs/<name>/` files with commit `d42901b` (runner change only; the OCR code is the same).

Same text from all three: the probe saves time, it does not change what is read. With `PROBE_K=2` the probe
lost its nominee on the camera snapshot (3 passes instead of 1), the clock-overlay failure the design recorded.

Per tag (`default`, normalised CER): spread 0.64, cluttered desk 0.41, decorative font 0.19, angle 90 0.23,
plain 0.06, hand covering 0.02, dim 0.00, text around picture 0.00. The spread (two pages read across as one
page) and desk text leaking into the page are the clear failures, as the weak-spot list expected; covered words
on the synthetic page barely registered because the "hand" hid mostly empty paper. These are synthetic numbers:
they test the workflow, not the reader.

## 4. The three trace/experiment tools for this job

### 4.1 MLflow (checked in the UI, T1)

- **Parameter comparison: strong.** Compare Runs gives a parallel-coordinates, scatter, box and contour plot of
  params (`pipeline`, `probe_k`, `structure`) against any metric, plus a side-by-side table. Git commit, dirty flag
  and pipeline are run tags, so they filter and group.
- **Per-tag breakdown: works by naming.** Each tag value is its own metric (`cer_norm.layout_spread`), so the
  compare table shows per-tag rows; there is no built-in "group by tag" over per-photo rows. The per-photo table
  (`per_photo.json`, `mlflow.log_table`) is an artifact, readable but not sliceable across runs.
- **Traces: good.** OTLP ingestion works with only the `x-mlflow-experiment-id` header; the span tree, attributes
  and timings show; `link_traces_to_run` ties each photo's trace to its run, and `log_feedback` puts the CER on
  the trace.
- **Structural comparison: indirect.** Two runs' traces can be opened side by side, but there is no diff of
  span trees; the extra `probe` span or the third `pass.scan` is seen by reading.
- **Images in traces: not through OTLP.** The thumbnail sent as a data URI shows as base64 text. MLflow 3.17 has
  trace attachments (`mlflow.tracing.attachments.Attachment`) that do render, but only through MLflow's own
  tracing SDK, not through plain OpenTelemetry.
- **Setup cost: lowest.** `pip install mlflow`, one SQLite file, one process; no Docker.
- **Watch out:** the UI opens an "MLflow Assistant" panel wired to Claude Code. It is idle until configured;
  configuring it would hand runs and traces to a cloud coding agent, so leave it off for this data.

### 4.2 FiftyOne (checked through its API; the grid shows real photos, so no screenshot was taken)

- The right tool for the photos themselves: 21 samples, tags as sample tags (`layout:spread`), one field set per
  pipeline (`ocr_default_text`, `_cer`, `_rotation`, `_alignment`, `_trace_id`), filter by tag, sort by CER
  (`ds.exists("ocr_default_cer").sort_by(...)` puts the spread, the decorative font on a cluttered desk and the
  cluttered desk first). The trace id field leads from a bad photo to its trace in the other tools.
- No text evaluator built in (as the research said): CER comes from jiwer and is written as plain fields.
- Telemetry flag works, but the app's page loads Google Fonts (§2).

### 4.3 Phoenix (checked in the UI, T1)

- **Traces: good.** Same span tree as MLflow; `session.id` groups a run's photos as a session.
- **Experiments: good for per-photo comparison.** A Phoenix dataset (the photos with truth) plus one experiment
  per run; the compare view puts the typed text, each pipeline's output and its CER/WER side by side per photo,
  with a mean-score chart per experiment, and filters on example metadata (the tags). Parameters are only
  experiment metadata: no parameter plot like MLflow's.
- **Per-tag breakdown: by filter**, one tag at a time; no table of all tags.
- **Images in traces: yes, with a condition.** A data-URI photo shows as base64 text on a normal (CHAIN) span;
  it is drawn as a picture when the span is of kind `LLM` and carries the OpenInference image message
  (`llm.input_messages.0.message.contents.0.message_content.image.image.url`). Verified with a synthetic photo.
- **Experiment timings are empty** here, because the experiment task only returns the output the traced run
  already produced; timings live in the traces.
- **Setup cost: low.** One container (or pip), SQLite inside.
- **Watch out:** without `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false` the UI fetches Google Fonts,
  `pypi.org/pypi/arize-phoenix/json` and `api.github.com/repos/Arize-ai/phoenix` from the browser (measured);
  with it, nothing. The "Ask PXI" assistant would need an LLM provider: leave it unconfigured.

### 4.4 Langfuse (checked in the UI, T1)

- **Traces: good**, with scores (`cer_norm`, `wer_norm`, `cer_raw`, `rotation_ok`) on each trace and a session
  per run.
- **Experiments: needed care.** Langfuse 4 runs in "events only" mode: the dataset-run-items REST call is
  accepted but nothing shows, and `GET /datasets/{name}/runs` answers that it is not available. An experiment is
  read from `langfuse.experiment.*` attributes on every span of the item's trace (what the v5 SDK's
  `run_experiment` sets); `run.py` now sets them with a span processor. After that the dataset lists the three
  experiments with item count, mean latency taken from the traces (2.7 / 2.9 / 3.9 s for default / probe-k2 /
  scan-only: the probe's saving is visible here, unlike in Phoenix) and the mean of each trace score. The mean of
  per-photo CER (0.13) is not the corpus CER MLflow shows (0.163: edits ÷ all reference characters); both are
  right, they weigh long pages differently.
- **Per-tag breakdown:** item metadata and trace tags filter; no ready per-tag table.
- **Images in traces: yes, through the SDK.** A raw data URI shows a broken-image icon; a `LangfuseMedia`
  object (SDK) is uploaded to the stack's MinIO and drawn in the trace (verified with a synthetic photo). Plain
  OpenTelemetry alone does not upload media.
- **Setup cost: highest.** Six containers (web, worker, Postgres, ClickHouse, Redis, MinIO), about 2 GB of images,
  secrets to manage; API changes between major versions (above).
- **Watch out:** the UI shows a "Star Langfuse" card whose badge loads from `img.shields.io` (hard-coded, no
  switch found in 4.70.0): the browser tells shields.io the PC's address. Langfuse's LLM features
  (`LANGFUSE_AI_*`, in-app agent, LLM-as-judge evaluators) stay unconfigured.

## 5. Egress results over the whole trial

| Check | Result |
|---|---|
| Tool containers → 1.1.1.1:443 (busybox in each container's namespace) | 9 × BLOCKED, gate control REACHED; same after the Docker restart (15:21) |
| Host eval processes (process-tree watch, 15:00–15:35: idle servers, UI use, the three runs of 15:22–15:33) | 0 outbound connections; the control at 15:33:54 was caught |
| MLflow UI | 127.0.0.1 only |
| Label Studio UI (login, data manager, image serving) | localhost only |
| Phoenix UI | Google Fonts, PyPI, GitHub API → none after `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false` |
| FiftyOne UI | Google Fonts (two stylesheets): **open, owner's choice** |
| Langfuse UI | `img.shields.io` stars badge: **open, owner's choice** |

The two open items are browser requests for page decoration: they carry no photo, text or score, but they do
tell Google and shields.io this PC's address and when a tool page is open. Ways to close them, for the owner to
choose: block the two hosts in the browser or the hosts file, or patch the installed FiftyOne page (it is
rewritten by every upgrade). Neither is applied.

## 6. Recommendation

| Need (this job) | MLflow | Phoenix | Langfuse |
|---|---|---|---|
| Parameter comparison across runs | **best** (plots, params table) | metadata only | metadata only |
| Structural comparison (which steps ran) | by reading traces | by reading traces | by reading traces |
| Traces of the internal steps | good | good | good |
| Per-tag breakdown | metric per tag, in the compare table | filter, one tag at a time | filter, one tag at a time |
| Per-photo output vs truth | artifact table | **best** (side-by-side compare) | good (item compare with scores) |
| Photo inside a trace | own SDK attachments only | LLM-kind span with image message | own SDK media only |
| Setup and upkeep | **lowest** (pip, SQLite) | low (1 container) | highest (6 containers, v4 API change) |
| Outbound by default | telemetry (off by env) | telemetry + UI fetches (off by env) | telemetry (off) + badge (open) |

For OCR evaluation now: **MLflow + FiftyOne + jiwer**, with Label Studio for typing truth. MLflow answers
"which settings are better, overall and per condition" in one screen and costs one process; FiftyOne answers
"which photos fail and why" with the photos in front of you. For the later LLM work (prompts, tool calls,
Brain conversations) Phoenix and Langfuse are built for exactly that; Phoenix is the cheaper of the two to keep
and showed the better per-example compare here, Langfuse has the richer scoring and annotation workflow but the
heaviest stack. Keep the OTel instrumentation tool-neutral (as `run.py` does) so the choice can wait. Adopting
any of them inside Leafi is a separate design decision.

## 7. Traps met

- `import mlflow` before `import fiftyone` breaks FiftyOne (`voxel51-eta` reads package metadata through the
  `importlib_metadata` backport that MLflow loads; key `author` missing). Import FiftyOne first.
- `import leafi` aliases `httpx` to `httpx2` (TD-1); the eval venv has the real httpx for the tools, so the
  runner registers `leafi` as a bare namespace and imports the OCR modules without `leafi/__init__.py`.
- Label Studio 1.23 creates its organisation with legacy API tokens off; `LABEL_STUDIO_ENABLE_LEGACY_API_TOKEN=true`
  must be set before the first start (it is read once, at organisation creation).
- FiftyOne cannot infer a field type from a first value of `None`; declare fields before writing.
- Langfuse 4 accepts `POST /api/public/dataset-run-items` and shows nothing (events-only mode); experiments come
  from `langfuse.experiment.*` span attributes. The Langfuse SDK's default base URL is the vendor cloud.
- Phoenix's UI calls PyPI, GitHub and Google Fonts until `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false`.
- A venv's `python.exe` on Windows is a launcher; a process watch must follow child processes.
- The camera photos' page text and the photos never appear in this document or in the agent's context: the
  runner prints numbers only, and UI checks used synthetic photos.
- Windows: 18080 was taken (`leafi-gatus`); 50000–50059 and 55000–56073 are reserved. The trial uses 19xxx.
