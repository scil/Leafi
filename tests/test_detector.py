"""The name detector (ADR-0018 §3, M5 design D11). The merge with the lists and the egress wiring run on a fake
detector; the real model (Presidio + spaCy en_core_web_sm 3.8.0 from `doctor --download --only names`) runs
only with LEAFI_HW_TESTS=1, including the check that building and using it opens no socket and no subprocess."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from leafi.core import learner_store
from leafi.core.config import Settings
from leafi.core.storage import Store
from leafi.privacy import detector, pseudonym
from leafi.privacy import settings as privacy
from leafi.privacy.detector import Span
from leafi.privacy.pseudonym import Mapping

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


class Fake:
    def __init__(self, *words: tuple[str, str]) -> None:
        self.words = words

    def spans(self, text: str) -> list[Span]:
        out = []
        for w, rep in self.words:
            i = text.find(w)
            if i >= 0:
                out.append(Span(i, i + len(w), rep))
        return out


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "leafi.db") as s:
        yield s


def test_detected_names_are_replaced_and_a_listed_name_wins_an_overlap(store):
    learner_store.create(store, "Rocco")
    p = pseudonym.build(store.conn, b"k" * 32)
    sur = p.names["learner:1"]
    m = Mapping()
    out = p.apply("Rocco played with Sophie at Riverside Park.", m,
                  detector=Fake(("Rocco played", "[name]"), ("Sophie", "[name]"), ("Riverside Park", "[place]")))
    assert out == f"{sur} played with [name] at [place]."
    assert m.back == {sur: "Rocco"}  # detector tokens are never reversed


def test_state_reports_the_effective_mode(tmp_path):
    s = Settings(_env_file=None, models_dir=tmp_path)
    assert detector.state(s) == "on, model missing: list only"
    assert detector.load(s) is None
    (tmp_path / "spacy" / detector.MODEL).mkdir(parents=True)
    (tmp_path / "spacy" / detector.MODEL / "meta.json").write_text("{}")
    assert detector.state(s) == "on"


async def test_egress_runs_the_detector_on_every_text_but_book_fields(settings):
    """ADR-0021 E2: the detector scans every `Text` that is not a book field, whatever its source; a book field
    (`book=True`, or a `page` provenance until E6) keeps its characters' names; plain strings get the lists only."""
    from leafi.privacy import destinations as dests
    from leafi.privacy import egress as eg
    from leafi.privacy import secret

    secret._forget_cache()
    store = Store(settings.db_path)
    rocco = learner_store.create(store, "Rocco")
    privacy.set_school(store, rocco, None)
    fake = dests.Destination("fake", "http", frozenset({"127.0.0.1"}), 9, frozenset({"generate"}), "cloud")
    e = eg.Egress(settings, registry={"fake": fake}, env_file=None)
    e._detector, e.detector_state = Fake(("Sophie", "[name]")), "ready"  # M7 D8: a loaded detector
    try:
        p = e.prepare("fake", "generate", eg.Outgoing(json={
            "said": eg.Text("I read with Sophie", "learner", (rocco,)),
            "page": eg.Text("Sophie opened the door", "page"),
            "title": eg.Text("Sophie's Day", book=True),
            "note": eg.Text("Sophie helped", "system"),
            "const": "Sophie"}), learner_id=rocco)
        assert p.json == {"said": "I read with [name]", "page": "Sophie opened the door", "title": "Sophie's Day",
                          "note": "[name] helped", "const": "Sophie"}
    finally:
        e.close()
        store.close()


@pytest.mark.hardware
def test_the_real_detector_finds_unlisted_people_and_places():
    if not (MODELS / "spacy" / detector.MODEL / "meta.json").exists():
        pytest.skip("python -m leafi doctor --download --only names")
    d = detector.load(Settings(_env_file=None, models_dir=MODELS))
    text = "After school I played with Tom and Sophie Turner, then we went to Oakridge Academy."
    hits = {text[s.start:s.end] for s in d.spans(text)}
    assert {"Tom", "Sophie Turner", "Oakridge Academy"} <= hits


@pytest.mark.hardware
def test_building_and_running_the_detector_opens_no_socket_and_no_subprocess(tmp_path):
    if not (MODELS / "spacy" / detector.MODEL / "meta.json").exists():
        pytest.skip("python -m leafi doctor --download --only names")
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        events = []
        sys.addaudithook(lambda e, a: events.append(e) if e in ("subprocess.Popen", "os.system", "os.exec",
                                                                    "os.posix_spawn") else None)
        from leafi.core import netguard
        netguard.install()  # LEAFI_NO_NETWORK: any non-loopback connect or name resolution raises
        from pathlib import Path
        from leafi.core.config import Settings
        from leafi.privacy import detector
        d = detector.load(Settings(_env_file=None, models_dir=Path({str(MODELS)!r})))
        print(len(d.spans("I met Tom at Oakridge Academy and emailed tom@example.com via www.example.com")))
        assert events == [], events
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    assert int(r.stdout.strip()) >= 1
