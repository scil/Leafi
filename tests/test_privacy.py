"""Egress policy (ADR-0018 §2–§3, security.md): (a) canaries recorded beneath the mediator — the bytes egress
actually puts on the wire — over a full harness session with the notifier and Anki, a Brain request carrying a
learner's own words, and operational alerts; (b) subprocess runs with LEAFI_NO_NETWORK=1."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from leafi.core.hub import Hub
from leafi.core.ports import AudioRef, Utterance, Word
from leafi.core.storage import Store
from leafi.core.text import typed_utterance
from leafi.devices.notifiers import NotifierDevice
from leafi.study import anki
from tests.fakes import RecordingFace, ScriptedListener
from tests.fakes.anki import FakeAnki

ROOT = Path(__file__).resolve().parents[1]
NAME, SCHOOL, LABEL = "Zephyrine", "Quillfield Academy", "Room 7B Wolverton"
AUDIO = b"CANARY-AUDIO-BYTES"
CANARIES = [NAME, SCHOOL, LABEL, "Quillfield", "Wolverton", AUDIO.decode()]
PAGE = (f"This book belongs to {NAME} of {SCHOOL}. The fox ran home.\n"
        f"It was late and dark. {LABEL} was written in pencil.")
ALLOWED_HOSTS = {"api.anthropic.com", "api.day.app", "api.telegram.org", "127.0.0.1"}


def _voice(text: str) -> Utterance:
    return Utterance(text, [Word(w) for w in text.split()], typed=False, audio_ref=AudioRef(AUDIO * 50))


def _claude_reply(request: httpx.Request) -> dict:
    body = json.loads(request.content)
    prompt = body["messages"][0]["content"]
    if "Intent: questions" in prompt:
        payload = {"questions": [{"question": "Where did the fox go?", "answer": "It ran home.",
                                  "keywords": [["home"]], "item_key": "home"}], "action": "ask"}
    else:
        payload = {"meaning_en": "A simple meaning.", "meaning_zh": "简单的意思。", "example": "An example.",
                   "follow_up": "", "action": "explain"}
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(payload)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


def _wire(settings):
    """Egress whose wire is recorded: every request here is exactly what would leave the machine."""
    from tests.egress_helpers import mock_egress

    sent: list[httpx.Request] = []

    def route(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if urlsplit(str(request.url)).hostname == "api.anthropic.com":
            return httpx.Response(200, json=_claude_reply(request), request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    return mock_egress(settings, route), sent


def _terms(settings, *items: tuple[str, str]) -> None:
    """The household's protected terms (`leafi privacy terms add`), set before the session."""
    from leafi.privacy import settings as privacy

    with Store(settings.db_path) as store:
        for term, kind in items:
            privacy.add_term(store, term, kind)


def _no_canary(sent, canaries=CANARIES) -> None:
    for r in sent:
        blob = (str(r.url) + "\n" + r.content.decode("utf-8", "replace")).lower()
        for c in canaries:
            assert c.lower() not in blob, (c, str(r.url))


async def test_no_canary_leaves_in_any_outbound_body(settings):
    settings.bark_url = "https://api.day.app/KEY"  # egress's bark destination comes from BARK_URL
    e, sent = _wire(settings)
    fake_anki = FakeAnki()
    settings.anthropic_api_key = "test-key-not-real"
    _terms(settings, (SCHOOL, "school"), (LABEL, "other"))
    notifier = NotifierDevice("parent", {"bark_url": "https://api.day.app/KEY", "telegram_bot_token": "T",
                                         "telegram_chat_id": "C", "egress": e}, settings=settings)
    listener = ScriptedListener([
        None,                                        # no objection: reading starts
        _voice(f"This book belongs to {NAME}"),
        _voice(f"what does {NAME} mean"),            # an explanation: no Brain until M7, so nothing leaves
        _voice(f"my name is {NAME} from {SCHOOL}"),  # learner free text: stays local
        _voice("of Quillfield Academy. The fox ran home."),
        _voice("It was late and dark."),
        _voice(f"{LABEL} was written in pencil."),
        "/stop",
    ], voice=True)
    hub = Hub(faces={"f": RecordingFace()}, notifiers={"parent": notifier}, policy="none",
              listeners={"voice": listener})
    from leafi.study.harness import loop

    store = Store(settings.db_path)
    await loop.run_session(loop.Env(store=store, hub=hub, settings=settings, listener=listener,
                                    anki=anki.AnkiClient(settings.anki_url,
                                                         transport=httpx.MockTransport(fake_anki.handle)),
                                    book_title="Canary book", page_text=PAGE, page_number=1, learner=NAME))

    hosts = {urlsplit(str(r.url)).hostname for r in sent}
    assert "api.anthropic.com" not in hosts  # the harness makes no Brain call until M7
    assert {"api.day.app", "api.telegram.org"} <= hosts, "the notifier path was not exercised"
    assert hosts <= ALLOWED_HOSTS, hosts
    _no_canary(sent)
    rows = [tuple(r) for r in store.all("SELECT destination, purpose, status FROM egress_log ORDER BY id")]
    assert rows == [("bark", "notify", "sent"), ("telegram", "notify", "sent")]


def test_the_parent_notification_names_a_learner_without_a_school_answer(settings):
    """Owner decision 2026-10-24 (M7 design A1, rev 6 review #17): with no school answer the notification now names
    the learner in a non-book `Text` (so egress replaces the name by its surrogate); a guest is "A reader"
    (ADR-0021: there is no `cloud.text` to switch off)."""
    from leafi.core import learner_store
    from leafi.core.ports import Counts
    from leafi.devices.notifiers import NotifierDevice

    e, _ = _wire(settings)
    store = Store(settings.db_path)
    kid = learner_store.create(store, NAME)
    guest = learner_store.create(store, "Guest", kind="guest")
    notifier = NotifierDevice(options={"egress": e}, settings=settings)
    body = notifier.body(Counts(kid, None, pages=1))
    assert body.value.startswith(NAME) and not body.is_book
    assert notifier.body(Counts(guest, None, pages=1)).startswith("A reader")


async def test_a_learners_own_words_leave_only_pseudonymised(settings):
    """ADR-0018 §3 lists, ADR-0021 E1: a learner's words reach the Brain with every listed name — the learner's, a
    sibling's in Chinese, a Latin name inside Chinese text, the school (answered here, so listed) — replaced, every
    time (content only, owner 2026-10-24)."""
    from leafi.core import learner_store
    from leafi.privacy import settings as privacy
    from leafi.privacy.egress import Outgoing, Text

    e, sent = _wire(settings)
    store = Store(settings.db_path)
    kid = learner_store.create(store, NAME)
    learner_store.create(store, "小明")
    privacy.set_school(store, kid, SCHOOL)
    said = f"我叫{NAME}，我和小明在{SCHOOL}读书。 {NAME}'s favourite word is fox."

    def brain_body() -> Outgoing:
        return Outgoing(path="/v1/messages", json={"model": "m", "max_tokens": 5, "messages": [
            {"role": "user", "content": Text(said)}]})

    p = e.prepare("anthropic", "generate", brain_body(), learner_id=kid)
    async with e.client("anthropic") as c:
        await c.send(p.request())
    (req,) = sent
    _no_canary(sent, [NAME, SCHOOL, "Quillfield", "小明"])
    assert "the school" in req.content.decode() and "'s favourite word" in req.content.decode()


async def test_operational_alerts_leave_only_as_catalog_sentences(settings, monkeypatch):
    """ADR-0016: a microphone loss whose message names the device and the learner, and a hostile keeper insert,
    reach Telegram only as fixed catalog sentences."""
    from urllib.parse import parse_qs

    from leafi.core import alerts
    from leafi.core.ports import ListenerLost
    from leafi.ops.alerts import deliver

    e, sent = _wire(settings)

    class DyingMic(ScriptedListener):
        async def next_utterance(self, timeout_s):
            raise ListenerLost(f"Microphone ({NAME}'s DJI Mic at {LABEL}) stopped")

    from leafi.study.harness import loop

    store = Store(settings.db_path)
    mic = DyingMic([], voice=True)
    await asyncio.wait_for(loop.run_session(loop.Env(
        store=store, hub=Hub(faces={"f": RecordingFace()}, policy="none", listeners={"mic": mic}), settings=settings,
        listener=mic, book_title="Canary book", page_text=PAGE, page_number=1, learner="Ada")), 10)
    alerts.insert(store, f"keeper-{NAME}", "down", f"{SCHOOL} exploded")  # what keep.ps1 could be made to pass

    notifier = NotifierDevice("ops", {"telegram_bot_token": "T", "telegram_chat_id": "C", "egress": e},
                              settings=settings)

    async def no_toast(text):
        return None

    before = len(sent)  # the session's own parent notification is not an alert
    assert await deliver(store, no_toast, notifier) == 2
    sent = sent[before:]
    bodies = [parse_qs(r.content.decode())["text"][0] for r in sent]
    assert bodies == [alerts.render("study-mic", "event", "mic_lost"), alerts.UNKNOWN]
    for r in sent:
        assert urlsplit(str(r.url)).hostname == "api.telegram.org"
        blob = (str(r.url) + "\n" + r.content.decode("utf-8", "replace")).lower()
        for c in CANARIES:
            assert c.lower() not in blob, c


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "TELEGRAM", "BARK"))}
    env.update(PYTHONPATH=str(ROOT), LEAFI_NO_NETWORK="1", DATA_DIR=str(tmp / "data"), CACHE_DIR=str(tmp / "cache"),
               PYTHONIOENCODING="utf-8", **extra)
    return env


def test_no_network_text_session_completes_with_the_cloud_backend_configured(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "devices.yml").write_text(
        "version: 1\nvoice_policy: none\ndevices:\n  - name: console\n    adapter: console\n"
        "    capabilities: [listener, face]\nstudy:\n  listener: console\n", encoding="utf-8")
    script = "The fox ran home.\nwhat does fox mean\nIt was late.\n/stop\n"
    page = tmp_path / "page.txt"
    page.write_text("The fox ran home. It was late.", encoding="utf-8")
    env = _env(tmp_path, ANTHROPIC_API_KEY="fake-key", BRAIN_BACKEND="claude", ANKI_URL="http://127.0.0.1:9",
               BRAIN_DEADLINE_S="5")
    r = subprocess.run([sys.executable, "-m", "leafi", "study", "--text", "--book", "Offline", "--page-text",
                        str(page), "--page", "1", "--learner", "Ada"], input=script, capture_output=True, text=True, cwd=tmp_path,
                       env=env, timeout=120, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "session 1 saved" in r.stdout
    assert "can't explain" in r.stdout  # the cloud call was denied → static fallback


def test_no_network_guard_denies_non_loopback_and_pronunciation_scores_offline(tmp_path):
    code = r"""
import asyncio, socket, sys, wave
from leafi.core import netguard
netguard.install()
try:
    socket.create_connection(("192.0.2.1", 80), timeout=1)
    sys.exit("sync connect was allowed")
except netguard.NetworkDenied:
    pass
import httpx
async def main():
    try:
        async with httpx.AsyncClient() as c:
            await c.get("http://192.0.2.1/")
        sys.exit("async connect was allowed")
    except (netguard.NetworkDenied, httpx.ConnectError):
        pass
    from leafi.core.config import Settings
    from leafi.core.ports import AudioRef
    from leafi.services import pronunciation
    with wave.open(sys.argv[1], "rb") as w:
        pcm = w.readframes(w.getnframes())
    scorer = pronunciation.REGISTRY.create("mock", Settings(_env_file=None))
    res = await scorer.score(AudioRef(pcm), "through")
    print("score", res.score)
asyncio.run(main())
"""
    from leafi.core.audio import silence, write_wav

    clip = tmp_path / "word.wav"
    write_wav(clip, silence(0.5), 16000)
    r = subprocess.run([sys.executable, "-c", code, str(clip)], capture_output=True, text=True, cwd=tmp_path,
                       env=_env(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout
    assert "score 0.9" in r.stdout


async def test_cloud_tts_receives_only_redacted_leafi_lines(settings, monkeypatch):
    """A Mouth with the edge backend: no canary and no learner-originated text reaches cloud TTS."""
    import edge_tts

    from leafi.services import tts
    from tests.fakes import FakeMouth

    spoken: list[str] = []

    class Recorder:
        def __init__(self, text, voice, rate="+0%"):
            spoken.append(text)

        async def save(self, path):
            Path(path).write_bytes(b"\x00" * 600)

    monkeypatch.setattr(edge_tts, "Communicate", Recorder)
    _terms(settings, (NAME, "name"), (SCHOOL, "school"), (LABEL, "other"))
    class GatedConsole:
        """Types the next line only after Leafi shows "listening" (like a person at the console)."""

        is_voice = False

        def __init__(self, lines):
            self.lines = list(lines)
            self.ready = asyncio.Event()

        async def next_utterance(self, timeout_s):
            await self.ready.wait()
            self.ready.clear()
            return typed_utterance(self.lines.pop(0) if self.lines else "/stop")

        async def pause(self):
            return None

        async def resume(self, after_s=0.0):
            return None

    class ListeningFace(RecordingFace):
        async def show(self, msg):
            await super().show(msg)
            if msg.kind == "listening":
                console.ready.set()

    mouth = FakeMouth(play_s=0.02)
    service = tts.create(settings, en="edge", zh="mock")  # a local backend exists for local-only lines
    face = ListeningFace()
    hub = Hub(faces={"f": face}, mouths={"cam": mouth}, policy="all", synthesizer=service)
    learner_word = "Zorblatt"
    script = [
        "",                                              # no objection: reading starts
        f"This book belongs to {NAME}",
        f"what does {NAME} mean",                       # explain_wait embeds the (page) target → redacted
        f"/fix belongs {learner_word}",                  # learner-typed, no name: may reach edge (ADR-0021 E7)
        "/stop",
    ]
    console = GatedConsole(script)
    hub.listeners = {"console": console}
    from leafi.study.harness import loop

    await asyncio.wait_for(loop.run_session(loop.Env(
        store=Store(settings.db_path), hub=hub, settings=settings, listener=console, book_title="Canary book",
        page_text=PAGE, page_number=1, learner="Ada")), 20)
    local = [text for text, _, _ in service.backends["zh"].calls]
    # a line holding a protected name is spoken locally, never sent pseudonymised (M5 design D13)
    assert any(t.startswith("Good question!") and NAME in t for t in local), local
    assert spoken, "the edge path was not exercised"
    assert any(learner_word in t for t in spoken + local), (spoken, local)  # routed by content, not by source
    assert any(learner_word in t for t in face.texts)  # and is shown on Faces
    assert len(mouth.played) > 3
    for text in spoken:  # no protected name ever reaches cloud TTS; a learner's plain word may (ADR-0021 E7)
        for c in CANARIES:
            assert c.lower() not in text.lower(), (c, text)
