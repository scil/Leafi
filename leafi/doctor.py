"""`python -m leafi doctor`: every backend as ok / missing package / missing model / disabled / deferred.

Leafi downloads nothing at runtime (ADR-0011): `doctor` prints what is missing, and `doctor --download` is the
one sanctioned downloader. It fetches only the fixed set below (release assets and model hubs), never at
inference time, and skips what is already present.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from pathlib import Path

from leafi.core.config import Settings

log = logging.getLogger("leafi.doctor")

SERVICES: list[tuple[str, str, str]] = [
    # (label, registry module, settings attribute holding the configured backend)
    ("asr", "leafi.services.asr", "asr_backend"),
    ("vad", "leafi.services.asr.vad", "asr_backend"),
    ("tts en", "leafi.services.tts", "tts_backend_en"),
    ("tts zh", "leafi.services.tts", "tts_backend_zh"),
    ("ocr", "leafi.services.ocr", "ocr_backend"),
    ("ocr second opinion", "leafi.services.ocr", "ocr_second_opinion"),
    ("pronunciation", "leafi.services.pronunciation", "pron_backend"),
    ("brain", "leafi.services.brain", "brain_backend"),
    ("brain local fallback", "leafi.services.brain", "brain_local_model"),
    ("book lookup", "leafi.services.catalog", "book_lookup"),
]

# What each row is for and whom it serves, printed under it so the owner can judge a missing item.
PURPOSE = {
    "asr": "turns the learner's reading aloud into words for alignment; serves the learner's reading session",
    "vad": "finds where speech starts and ends so the ASR gets whole utterances; serves the learner's session",
    "tts en": "Leafi's English voice: models a word in practice, reads aloud; serves the learner",
    "tts zh": "Leafi's Chinese voice for explanations (edge: the text goes to Microsoft); serves the learner",
    "ocr": "reads the page text from the camera image, so Leafi knows what should be read; serves the learner",
    "ocr second opinion": "a second OCR on hard pages (not built yet); would serve the learner",
    "pronunciation": "scores a practised word's sound, only with PRON_AUTO_JUDGE; serves the learner's practice",
    "brain": "Claude: word explanations and comprehension questions, text only; serves the learner",
    "brain local fallback": "a local Ollama model used when Claude is unreachable; serves the learner",
    "book lookup": "finds a book's title from its ISBN on Open Library; serves the owner adding books",
    "sqlite": "the database of sessions, miscues and progress (data/leafi.db); serves the owner and every session",
    "names": ("finds people, schools and places nobody listed in a learner's own words before they reach a cloud "
              "service (ADR-0018 §3); without its model only listed names are replaced; serves each child's privacy"),
    "schools": ("every learner's school name or \"no school\", replaced before any text leaves (ADR-0018 §3); a "
                "learner without an answer keeps their own words off the cloud; serves each child's privacy"),
    "wordlists": ("tells a misread real word (a candidate error to practise) from a garbled one (only observed); "
                  "later ranks new words by level (M7); serves the learner's error detection"),
}

KOKORO_RELEASE ="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def rows(settings: Settings) -> Iterator[tuple[str, str, str, str]]:
    for label, module, attr in SERVICES:
        backend = str(getattr(settings, attr) or "")
        if attr == "brain_local_model":
            backend = "ollama" if backend else ""
        if attr == "ocr_second_opinion" and not backend:
            yield label, "-", "deferred", "qwen_vl second opinion is deferred in v1 (ADR-0011)"
            continue
        if label == "vad":
            if backend in ("", "off", "mock"):
                yield label, "-", "disabled", "energy end-pointer (mock ASR)"
                continue
            backend = "silero"
        if not backend or backend == "off":
            yield label, backend or "-", "disabled", ""
            continue
        try:
            mod = importlib.import_module(module)
            if label == "vad":
                state, detail = mod.status(settings)
            else:
                state, detail = mod.REGISTRY.status(backend, settings)
        except (ImportError, LookupError) as e:
            state, detail = "error", str(e)
        yield label, backend, state, detail


def sqlite_line(settings: Settings) -> str:
    """The SQLite library and the journal mode of data/leafi.db (ADR-0019): WAL only under a fixed library."""
    import sqlite3

    from leafi.core import storage

    version = storage._library_version()
    mode, schema = "not created", ""
    if settings.db_path.exists():
        try:
            c = sqlite3.connect(f"file:{settings.db_path.resolve().as_posix()}?mode=ro", uri=True)
            try:
                mode = c.execute("PRAGMA journal_mode").fetchone()[0]
                n = c.execute("PRAGMA user_version").fetchone()[0]
                learner = " --learner and the child's first name in quotes" if n < 5 else ""
                schema = f" schema={n}" + ("" if n == storage.SCHEMA_VERSION else
                                           f" (run python -m leafi migrate{learner}, ADR-0018 §7.2)")
            finally:
                c.close()
        except sqlite3.Error as e:
            mode = f"unreadable ({e})"
    v = ".".join(map(str, version))
    mode += schema
    if storage.wal_safe(version):
        return f"{'sqlite':<22}{v:<16}{'ok':<16}leafi.db journal_mode={mode}"
    return (f"{'sqlite':<22}{v:<16}{'WAL off':<16}has the WAL-reset bug; leafi.db journal_mode={mode}; "
            "replace the Python install's DLLs\\sqlite3.dll with 3.51.3+ (ADR-0019 §2)")


def names_line(settings: Settings) -> str:
    """The name detector's effective state, apart from the configured value (M5 design D11)."""
    from leafi.privacy import detector

    st = detector.state(settings)
    if st == "on":
        return f"{'names':<22}{'presidio+spacy':<16}{'ok':<16}{detector.MODEL}"
    if st == "off":
        return f"{'names':<22}{'presidio+spacy':<16}{'off':<16}PRIVACY_NAME_DETECTOR is off: listed names only"
    return (f"{'names':<22}{'presidio+spacy':<16}{'missing model':<16}only listed names are replaced; "
            "python -m leafi doctor --download --only names")


def schools_line(settings: Settings) -> str:
    """Learners without a school answer (design D10), read-only so it works on a file not yet migrated."""
    import json
    import sqlite3

    if not settings.db_path.exists():
        return f"{'schools':<22}{'leafi.db':<16}{'ok':<16}no learners yet"
    try:
        c = sqlite3.connect(f"file:{settings.db_path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            rows = c.execute("SELECT display_name, settings FROM learners WHERE kind='learner' AND forgetting=0 "
                             "ORDER BY id").fetchall()
        finally:
            c.close()
    except sqlite3.Error as e:
        return f"{'schools':<22}{'leafi.db':<16}{'unknown':<16}{e}"
    missing = [n for n, s in rows if json.loads(s or "{}").get("privacy.school") is None]
    if not missing:
        return f"{'schools':<22}{'leafi.db':<16}{'ok':<16}{len(rows)} learner(s) answered; python -m leafi privacy schools"
    first = missing[0]
    return (f"{'schools':<22}{'leafi.db':<16}{'not answered':<16}{', '.join(missing)}: set each with e.g. "
            f"python -m leafi privacy learner \"{first}\" school, then the school's name in quotes (or none), "
            "then --yes")


def wordlist_line(settings: Settings) -> str:
    from leafi.services.wordinfo import WORDLIST_FILES

    d = wordlist_dir(settings)
    missing = [n for n in WORDLIST_FILES if not (d / n).exists()]
    yle = "YLE pdf present" if (d / "yle-wordlists-2018.pdf").exists() else "YLE pdf not fetched (optional)"
    if not missing:
        return f"{'wordlists':<22}{'scowl+cyplex':<16}{'ok':<16}{yle}"
    return (f"{'wordlists':<22}{'scowl+cyplex':<16}{'missing model':<16}{', '.join(missing)}; is_word falls back to "
            f"lemminflect (doctor --download --only wordlists); {yle}")


def report(settings: Settings) -> str:
    lines = [f"{'service':<22}{'backend':<16}{'state':<16}detail"]

    def add(label: str, line: str) -> None:
        lines.append(line)
        lines.append(f"{'':<4}for: {PURPOSE[label]}")

    for label, backend, state, detail in rows(settings):
        add(label, f"{label:<22}{backend:<16}{state:<16}{detail}")
    add("sqlite", sqlite_line(settings))
    add("names", names_line(settings))
    add("schools", schools_line(settings))
    add("wordlists", wordlist_line(settings))
    if settings.anki_url:
        from leafi.study.anki import NOTICE

        lines.append(f"NOTE (Anki): {NOTICE}")
    if settings.pron_auto_judge:
        lines.append("NOTE: PRON_AUTO_JUDGE is on; it requires the evaluation threshold in ADR-0011.")
    return "\n".join(lines)


# ---------------------------------------------------------------- downloads


_SETTINGS: Settings | None = None  # set by `download`, for `_fetch`'s egress


def _fetch(url: str, dest: Path) -> None:
    """One fixed file through `leafi.privacy.egress` (purpose `ops`, M5 design D16): the URL's host must be a
    destination of the registry, and a redirect is followed only to a host that destination lists."""
    import asyncio
    from urllib.parse import urlsplit

    from leafi.privacy import destinations, runtime

    e = runtime.get(_SETTINGS or Settings())
    u = urlsplit(url)
    dest_rec = destinations.find(e.registry, u.hostname or "", u.port or 443)
    if dest_rec is None:
        raise RuntimeError(f"{u.hostname} is no egress destination (privacy/destinations.py)")
    if u.query:
        raise RuntimeError(f"{url}: a download URL with a query is not supported")
    print(f"  fetching {url}")
    asyncio.run(e.fetch(dest_rec.name, u.path, dest))


def download_asr(settings: Settings) -> str:
    from leafi.services.asr import sherpa

    d = Path(settings.asr_model_dir)
    if all((d / f).exists() for f in sherpa.FILES):
        return "present"
    with tempfile.TemporaryDirectory(prefix="leafi-asr-") as tmp:
        archive = Path(tmp) / "model.tar.bz2"
        _fetch(sherpa.DOWNLOAD, archive)
        with tarfile.open(archive, "r:bz2") as tar:
            members = [m for m in tar.getmembers()
                       if m.isfile() and Path(m.name).name in sherpa.FILES and ".." not in m.name]
            d.mkdir(parents=True, exist_ok=True)
            for m in members:
                with tar.extractfile(m) as src, open(d / Path(m.name).name, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    return "downloaded"


def download_vad(settings: Settings) -> str:
    from leafi.services.asr import vad

    p = vad.model_path(settings)
    if p.exists():
        return "present"
    _fetch(vad.DOWNLOAD, p)
    return "downloaded"


def download_tts(settings: Settings) -> str:
    from leafi.services.tts import kokoro

    got = []
    for p in kokoro._paths(settings):
        if not p.exists():
            _fetch(KOKORO_RELEASE + p.name, p)
            got.append(p.name)
    return "downloaded " + ", ".join(got) if got else "present"


def download_pronunciation(settings: Settings) -> str:
    from leafi.services.pronunciation import openpronounce as op

    state, _ = op.status(settings)
    if state == "ok":
        return "present"
    from leafi import bootstrap

    if bootstrap.enforcing():  # huggingface_hub's own client is not mediated
        return ("not downloaded: the mediated Hugging Face download is not built yet (M5 design D15); "
                "these checkpoints cannot be fetched while the socket guard enforces")
    from huggingface_hub import snapshot_download  # lazy; installed with openpronounce

    cache = op.hf_dir(settings)
    cache.mkdir(parents=True, exist_ok=True)
    for repo in op.HF_REPOS:
        print(f"  fetching {repo}")
        path = snapshot_download(repo, cache_dir=str(cache), allow_patterns=["*.json", "*.txt", "*.safetensors"])
        if not any(Path(path).glob("*.safetensors")):
            snapshot_download(repo, cache_dir=str(cache), allow_patterns=["*.json", "*.txt", "pytorch_model.bin"])
    return "downloaded"


def download_ocr(settings: Settings) -> str:
    """RapidOCR fetches its ONNX files on first use into its package; provision PP-OCRv5 (en) and v6 now."""
    from leafi.services.ocr import rapidocr as backend

    done = []
    for version in backend.VERSIONS:
        engine = backend.engine(version)
        engine(_probe_image())  # models load (and download once) on the first call, not in the constructor
        done.append(version)
    return "present: " + ", ".join(done)


def _probe_image() -> bytes:
    import io

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (480, 120), "white")
    ImageDraw.Draw(img).text((20, 30), "Leafi page 12", fill="black", font=ImageFont.load_default(size=40))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


SCOWL_RELEASE = "https://raw.githubusercontent.com/en-wl/wordlist-diff/rel-2026.02.25/"  # SCOWL size 60, MIT-like
CYPLEX_CSVS = {"main_cyplex79.csv": "https://osf.io/download/s73vd/",  # CYP-LEX 7-9, CC BY 4.0 (OSF tnu8k)
               "main_cyplex1012.csv": "https://osf.io/download/yhrk8/"}  # CYP-LEX 10-12
CYPLEX_NOTICE = ("cyplex.txt is adapted from CYP-LEX (main_cyplex79.csv, main_cyplex1012.csv; word forms with Count "
                 ">= {min}, case-folded, other columns dropped): Korochkina, Marelli, Brysbaert & Rastle (2024), "
                 "The Children and Young People's Books Lexicon (CYP-LEX), QJEP 77(12), "
                 "doi:10.1177/17470218241229694; data https://osf.io/tnu8k/ under CC BY 4.0 "
                 "(https://creativecommons.org/licenses/by/4.0/).\n")
YLE_PDF = "https://www.cambridgeenglish.org/pl/Images/149681-yle-flyers-word-list.pdf"  # (c) UCLES, never bundled


def wordlist_dir(settings: Settings) -> Path:
    return Path(settings.models_dir) / "wordlists"


def download_wordlists(settings: Settings) -> str:
    """`WordInfo.is_word`'s lists (plan M0.2): SCOWL size 60 en_GB-ise + en_US with its copyright notice, and a
    CYP-LEX extract built locally from the 7-9 and 10-12 bands (the CSVs are kept for the level band)."""
    from leafi.services import wordinfo

    d = wordlist_dir(settings)
    got = []
    for name, src in (("en_GB-ise.txt", "en_GB-ise.txt"), ("en_US.txt", "en_US.txt"),
                      ("SCOWL-COPYRIGHT.txt", "Copyright")):
        if not (d / name).exists():
            _fetch(SCOWL_RELEASE + src, d / name)
            got.append(name)
    if not (d / "cyplex.txt").exists():
        csvs = []
        for name, url in CYPLEX_CSVS.items():
            p = d / "cyplex" / name
            if not p.exists():
                _fetch(url, p)
            csvs.append(p)
        n = wordinfo.build_cyplex(csvs, d / "cyplex.txt")
        (d / "CYPLEX-NOTICE.txt").write_text(CYPLEX_NOTICE.format(min=wordinfo.CYPLEX_MIN_COUNT), encoding="utf-8")
        got.append(f"cyplex.txt ({n} words)")
    return "downloaded " + ", ".join(got) if got else "present"


def download_yle(settings: Settings) -> str:
    """Cambridge YLE wordlists PDF (2018) for the level band, for the household's own use (owner decision M0 (2)):
    optional, fetched only when named; a missing file leaves banding on CYP-LEX alone."""
    p = wordlist_dir(settings) / "yle-wordlists-2018.pdf"
    if p.exists():
        return "present"
    _fetch(YLE_PDF, p)
    return "downloaded"


SPACY_MODEL = "en_core_web_sm-3.8.0"
SPACY_WHEEL = ("https://github.com/explosion/spacy-models/releases/download/"
               f"{SPACY_MODEL}/{SPACY_MODEL}-py3-none-any.whl")  # MIT; a wheel is a zip, unpacked, never pip-installed


def spacy_model_dir(settings: Settings) -> Path:
    return Path(settings.models_dir) / "spacy" / SPACY_MODEL


def download_spacy(settings: Settings) -> str:
    """The name detector's English model (ADR-0018 §3, M5 design D11): the wheel's model folder only, so spaCy
    loads it from a path and never resolves or downloads a package by name."""
    import zipfile

    d = spacy_model_dir(settings)
    if (d / "meta.json").exists():
        return "present"
    prefix = f"en_core_web_sm/{SPACY_MODEL}/"
    with tempfile.TemporaryDirectory(prefix="leafi-spacy-") as tmp:
        wheel = Path(tmp) / "model.whl"
        _fetch(SPACY_WHEEL, wheel)
        part = d.with_name(d.name + ".part")
        shutil.rmtree(part, ignore_errors=True)
        with zipfile.ZipFile(wheel) as z:
            for name in z.namelist():
                if not name.startswith(prefix) or name.endswith("/") or ".." in name:
                    continue
                target = part / name[len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        if not (part / "meta.json").exists():
            raise RuntimeError(f"{SPACY_WHEEL} holds no {prefix}meta.json")
        shutil.rmtree(d, ignore_errors=True)
        part.replace(d)
    return "downloaded"


SPEECHOCEAN762 = "https://www.openslr.org/resources/101/speechocean762.tar.gz"  # SLR101, CC BY 4.0


def eval_dir(settings: Settings, name: str) -> Path:
    return Path(settings.data_dir) / "evals" / name


def download_speechocean762(settings: Settings) -> str:
    """Public evaluation data for ADR-0013's false-alarm budget (plan M4.4a): 520 MB, CC BY 4.0 (Zhang et al.,
    Interspeech 2021). Learner-free public audio, stored under data/ (gitignored)."""
    d = eval_dir(settings, "speechocean762")
    if (d / "resource" / "scores.json").exists():
        return "present"
    d.parent.mkdir(parents=True, exist_ok=True)
    archive = d.parent / "speechocean762.tar.gz"
    if not archive.exists():
        _fetch(SPEECHOCEAN762, archive)
    root = d.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar.getmembers():
            name = Path(m.name)
            rel = Path(*name.parts[1:]) if name.parts and name.parts[0] == "speechocean762" else name
            target = (d / rel).resolve()
            if not (m.isfile() or m.isdir()) or not str(target).startswith(str(root)):
                continue  # links, devices and paths leaving the folder are never extracted
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    archive.unlink()
    return "downloaded"


DOWNLOADS = [("asr", download_asr), ("vad", download_vad), ("tts en", download_tts),
             ("pronunciation", download_pronunciation), ("ocr", download_ocr), ("wordlists", download_wordlists),
             ("names", download_spacy)]
# Evaluation data and the YLE PDF: fetched only when named in `--only`, never by a plain `--download`.
OPTIONAL_DOWNLOADS = [("yle", download_yle), ("speechocean762", download_speechocean762)]


def download(settings: Settings, only: set[str] | None = None) -> list[tuple[str, str]]:
    global _SETTINGS
    _SETTINGS = settings
    out = []
    for label, fn in DOWNLOADS + OPTIONAL_DOWNLOADS:
        if (only and label not in only) or (not only and (label, fn) in OPTIONAL_DOWNLOADS):
            continue
        try:
            out.append((label, fn(settings)))
        except Exception as e:  # noqa: BLE001 - report and continue with the next model
            out.append((label, f"failed: {type(e).__name__}: {e}"))
    return out
