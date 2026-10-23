"""Settings for the Leafi process (owner of `.env` for the study track; see docs/architecture/config.md).

This is the only module in `leafi/` that reads the process environment. Everything else receives a
`Settings` instance (dependency injection), so tests build their own with `Settings(_env_file=None)`.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- paths ----
    data_dir: Path = Path("data")
    cache_dir: Path = Path("cache")
    models_dir: Path = Path("models")
    devices_file: Path = Path("config/devices.yml")

    # ---- camera / go2rtc (shared with the habit track's .env names) ----
    go2rtc_url: str = "http://127.0.0.1:2984"
    stream_name: str = "cam_xiaomi"
    speaker_audio_codec: str = "opus"
    speaker_src_dir: str = ""

    # ---- services ----
    asr_backend: str = "sherpa"
    asr_model_dir: Path = Path("models/asr/parakeet-tdt-0.6b-v2-int8")
    asr_hotwords: str = "off"
    asr_threads: int = 4  # P-1: 12-word sentence 0.17 s at 2 threads, 0.12 s at 4, 0.09 s at 8 (CPU)
    vad_silence_s: float = 0.6  # Silero: silence that closes an utterance (sentence completion is SENTENCE_PAUSE_S)
    vad_threshold: float = 0.5
    tts_backend_en: str = "kokoro"
    tts_backend_zh: str = "edge"
    tts_voice_en_kokoro: str = "af_heart"
    tts_voice_zh_edge: str = "zh-CN-YunxiNeural"
    tts_voice_en_edge: str = "en-US-JennyNeural"
    ocr_backend: str = "rapidocr"
    ocr_version: str = "PP-OCRv6"  # PP-OCRv6 (in the wheel) | PP-OCRv5 (doctor --download); prototype P-3
    ocr_auto_rotate: bool = True  # P-3: the book lay sideways to the camera; try 90/180/270 when 0 reads poorly
    page_diff_threshold: float = 6.0  # P-3: desk camera noise 2.3–3.0 between stills; a hand 37–66; rendered pages 1.7
    ocr_second_opinion: str = ""
    ocr_min_confidence: float = 0.85
    ocr_snap: str = "advisory"
    pron_backend: str = "openpronounce"
    pron_auto_judge: bool = False
    brain_backend: str = "claude"
    study_brain_model: str = "claude-opus-5-5"  # STUDY_BRAIN_MODEL; the habit track keeps BRAIN_MODEL
    brain_model_cheap: str = "claude-haiku-5-5"
    brain_deadline_s: float = 12.0
    brain_local_model: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    anthropic_api_key: str = ""
    book_lookup: str = "off"

    # ---- privacy ----
    redact_terms: str = ""
    audio_keep_clips: bool = False
    eval_transcripts: bool = False
    leafi_no_network: bool = False
    leafi_debug_text: bool = False

    # ---- notifications (text only in the study track) ----
    bark_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ---- study timing ----
    study_idle_s: float = 180.0
    practice_retry_s: float = 10.0
    check_answer_s: float = 20.0
    say_timeout_s: float = 20.0
    sentence_pause_s: float = 1.2
    page_poll_s: float = 1.0  # how often the session checks the Eye for a physical page turn
    study_language: str = "en"
    pages_retain_days: int = 7
    review_known_interval_days: int = 21
    review_max_cards: int = 5
    guest_keep_days: int = 7  # ADR-0018 §1: an unconfirmed guest's session is kept this long; 0 = delete at wrap

    # ---- Anki ----
    anki_url: str = "http://127.0.0.1:8765"
    anki_deck: str = "Leafi"
    anki_model: str = "问答题"

    # ---- speech lease ----
    lease_ttl_s: float = 60.0

    # ---- supervisor (ADR-0016) ----
    # habit-agent is opt-in: it makes the camera speak on its schedule (AGENTS.md: never unasked); also: ollama
    supervise: str = "docker,camera,frigate,mosquitto,gatus"
    # timings (ADR-0016 "Timing settings"): validated together by leafi/ops/timing.py; a value that breaks an
    # invariant falls back to its default and the supervision-timing check alerts
    supervisor_poll_s: float = 60.0
    supervisor_bad_streak: int = 2
    supervisor_max_recoveries: int = 3
    supervisor_healthy_s: float = 600.0
    supervisor_grace: str = "camera=90,habit-agent=90,docker=180,frigate=120,mosquitto=60,gatus=60,ollama=60"
    supervisor_resume_gap_s: float = 180.0
    supervisor_resume_grace_s: float = 120.0
    task_repeat_min: int = 5
    keep_backoff_s: str = "5,30,120,300"
    keep_crash_exits: int = 3
    keep_crash_window_min: float = 30.0
    supervisor_port: int = 18771  # POST /rearm only; outside the Windows excluded port ranges (2026-10-20)
    go2rtc_exe: Path = Path("tools/go2rtc/go2rtc.exe")
    go2rtc_config: Path = Path("tools/go2rtc/go2rtc-host.yaml")
    frigate_url: str = "http://127.0.0.1:15000"
    frigate_camera: str = "hallway"  # the Frigate camera fed by STREAM_NAME (config/frigate/config.yml)
    mqtt_port: int = 18830  # host port of mosquitto (docker-compose.yml)
    docker_desktop_exe: str = ""  # empty: found next to the docker CLI (scoop) or under Program Files
    # configuration checks, heartbeat and the read-only Gatus dashboard (ADR-0016)
    checks_every_s: float = 900.0
    go2rtc_sha256: str = "e4e5fc2d75094ffa5034bceaf00b4e06a643712e705646648169d5f7d73321c3"  # patched build, 2026-10-21
    active_hours: str = "7-21"  # Windows Update active hours must cover these hours
    min_free_gb: float = 5.0
    required_channels: str = "telegram,heartbeat"  # remove one to accept toast-only / no heartbeat
    heartbeat_url: str = ""  # Healthchecks.io ping URL (hc-ping.com/<uuid>); empty: no heartbeat
    gatus_url: str = "http://127.0.0.1:18080"
    gatus_token: str = ""  # shared with the gatus container (docker-compose.yml); empty: no dashboard pushes

    @property
    def docker_settings_file(self) -> Path:
        return Path(os.environ.get("APPDATA", "")) / "Docker" / "settings-store.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "leafi.db"

    @property
    def lease_path(self) -> Path:
        return self.data_dir / "leafi.lock"

    def redact_list(self) -> list[str]:
        return [t.strip() for t in self.redact_terms.split(",") if t.strip()]


def env_lookup(name: str, settings: Settings | None = None, env_file: Path | None = Path(".env")) -> str | None:
    """Value of `${NAME}` for config/devices.yml: process env, then `.env`, then a Settings field."""
    if name in os.environ:
        return os.environ[name]
    if env_file is not None and env_file.exists():
        from dotenv import dotenv_values

        values = dotenv_values(env_file, encoding="utf-8")
        if values.get(name) is not None:
            return values[name]
    if settings is not None:
        field = name.lower()
        if field in Settings.model_fields:
            return str(getattr(settings, field))
    return None


def env_overrides(keys: list[str]) -> list[str]:
    """Which of these `.env` keys this process's environment shadows (pydantic-settings: the environment wins).
    Names only, never values."""
    present = {k.upper() for k in os.environ}
    return [k for k in keys if k.upper() in present]


def hardware_tests_enabled() -> bool:
    return os.environ.get("LEAFI_HW_TESTS") == "1"


def export_for_libraries(values: dict[str, str], *, force: set[str] = frozenset()) -> dict[str, str]:
    """Some third-party libraries (OpenPronounce, Hugging Face hub, phonemizer) are configured only through
    the process environment. This is the one place in `leafi/` that writes it: a name already set by the
    owner wins unless it is in `force` (offline switches). Returns the effective values."""
    out = {}
    for name, value in values.items():
        if name in force or not os.environ.get(name):
            os.environ[name] = value
        out[name] = os.environ[name]
    return out
