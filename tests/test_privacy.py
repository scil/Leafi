"""Egress policy (ADR-0011, security.md): (a) outbound recorder with canaries over a full session that uses
the real Claude backend, notifier and Anki client; (b) subprocess runs with LEAFI_NO_NETWORK=1."""

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
from leafi.services import brain as brain_service
from leafi.study import anki
from leafi.study.session import StudySession
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


async def test_no_canary_leaves_in_any_outbound_body(settings, monkeypatch):
    sent: list[httpx.Request] = []
    fake_anki = FakeAnki()

    def route(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        host = urlsplit(str(request.url)).hostname
        if host == "api.anthropic.com":
            return httpx.Response(200, json=_claude_reply(request), request=request)
        if host == "127.0.0.1":
            resp = fake_anki.handle(request)
            resp.request = request
            return resp
        return httpx.Response(200, json={}, request=request)

    async def async_send(self, request, **kw):
        return route(request)

    def sync_send(self, request, **kw):
        return route(request)

    monkeypatch.setattr(httpx.AsyncClient, "send", async_send)
    monkeypatch.setattr(httpx.Client, "send", sync_send)

    settings.anthropic_api_key = "test-key-not-real"
    settings.redact_terms = f"{NAME},{SCHOOL},{LABEL}"
    claude = brain_service.REGISTRY.create("claude", settings)
    notifier = NotifierDevice("parent", {"bark_url": "https://api.day.app/KEY", "telegram_bot_token": "T",
                                         "telegram_chat_id": "C"})
    hub = Hub(faces={"f": RecordingFace()}, notifiers={"parent": notifier}, policy="none")
    script = [
        _voice(f"This book belongs to {NAME}"),
        _voice(f"what does {NAME} mean"),            # target from the page → redacted before leaving
        _voice(f"my name is {NAME} from {SCHOOL}"),  # learner free text: stays local
        _voice("of Quillfield Academy. The fox ran home."),
        _voice("It was late and dark."),
        _voice(f"{LABEL} was written in pencil."),
        _voice(f"{NAME} lives at home with {SCHOOL} friends"),  # CHECK answer: compared locally
        "/stop",
    ]
    session = StudySession(store=Store(settings.db_path), hub=hub, settings=settings, brain=claude,
                           anki_client=anki.AnkiClient(settings.anki_url), listener=ScriptedListener(script, voice=True))
    await session.run(book_title="Canary book", page_text=PAGE, page_number=1)

    hosts = {urlsplit(str(r.url)).hostname for r in sent}
    assert "api.anthropic.com" in hosts, "the Claude path was not exercised"
    assert hosts <= ALLOWED_HOSTS, hosts
    claude_bodies = [r.content.decode() for r in sent if urlsplit(str(r.url)).hostname == "api.anthropic.com"]
    assert any("[name]" in json.loads(b)["messages"][0]["content"] for b in claude_bodies)  # redacted, not absent
    for r in sent:
        if urlsplit(str(r.url)).hostname == "127.0.0.1":
            continue  # AnkiConnect on loopback is inside the LAN boundary
        blob = (str(r.url) + "\n" + r.content.decode("utf-8", "replace")).lower()
        for c in CANARIES:
            assert c.lower() not in blob, (c, str(r.url))


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
                        str(page), "--page", "1"], input=script, capture_output=True, text=True, cwd=tmp_path,
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
    settings.redact_terms = f"{NAME},{SCHOOL},{LABEL}"
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
        f"This book belongs to {NAME}",
        f"what does {NAME} mean",                       # explain_wait embeds the (page) target → redacted
        f"/fix belongs {learner_word}",                  # learner-typed correction text → local-only line
        "/stop",
    ]
    console = GatedConsole(script)
    session = StudySession(store=Store(settings.db_path), hub=hub, settings=settings,
                           brain=brain_service.REGISTRY.create("mock", settings), listener=console)
    await asyncio.wait_for(session.run(book_title="Canary book", page_text=PAGE, page_number=1), 20)
    assert "EXPLAIN" in session.flags.transitions and "CORRECT" in session.flags.transitions
    assert any(t.startswith("Good question!") and "[name]" in t for t in spoken), spoken  # redacted, sent
    local = [text for text, _, _ in service.backends["zh"].calls]
    assert any(learner_word in t for t in local), local  # the correction line went to the local backend
    assert any(learner_word in t for t in face.texts)  # and is shown on Faces
    assert len(mouth.played) > 3
    for text in spoken:
        for c in [*CANARIES, learner_word]:
            assert c.lower() not in text.lower(), (c, text)
