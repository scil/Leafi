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
    tts_backend_en: str = "kokoro"
    tts_backend_zh: str = "edge"
    tts_voice_en_kokoro: str = "af_heart"
    tts_voice_zh_edge: str = "zh-CN-YunxiNeural"
    tts_voice_en_edge: str = "en-US-JennyNeural"
    ocr_backend: str = "rapidocr"
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
    study_language: str = "en"
    pages_retain_days: int = 7
    review_known_interval_days: int = 21
    review_max_cards: int = 5

    # ---- Anki ----
    anki_url: str = "http://127.0.0.1:8765"
    anki_deck: str = "Leafi"
    anki_model: str = "问答题"

    # ---- speech lease ----
    lease_ttl_s: float = 60.0

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


def hardware_tests_enabled() -> bool:
    return os.environ.get("LEAFI_HW_TESTS") == "1"
