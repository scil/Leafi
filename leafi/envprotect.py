"""The protection floor for `.env` editing (design §8.7): the manifest must be at least this strict.

These lists are deliberately independent of `config/env-schema.json`: weakening a protection is a change to this
file, visible in review, never a quiet manifest edit. `leafi.envedit.agreement` enforces them on every editor load,
and `tests/test_env_protections.py` proves them behaviourally.
"""

SECRET_FLOOR = frozenset({"TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "CAM_PASSWORD", "TAPO_CLOUD_PASSWORD",
                          "GATUS_TOKEN", "BARK_URL", "HEARTBEAT_URL"})

# ADR-0011: what may leave the house
PRIVACY_FLOOR = frozenset({"NOTIFY_WITH_SNAPSHOT", "BOOK_LOOKUP", "AUDIO_KEEP_CLIPS", "EVAL_TRANSCRIPTS",
                           "REDACT_TERMS", "BRAIN_BACKEND", "STUDY_BRAIN_MODEL", "TTS_BACKEND_EN", "TTS_BACKEND_ZH"})

# ADR-0011 / ADR-0003 release gates: (key, a value that must be refused); "*" = any non-empty value
GATE_FLOOR = (("PRON_AUTO_JUDGE", "true"), ("ASR_HOTWORDS", "lexicon"), ("OCR_SNAP", "auto"),
              ("ASR_BACKEND", "whisper"), ("OCR_BACKEND", "qwen_vl"), ("BRAIN_BACKEND", "ollama"),
              ("OCR_SECOND_OPINION", "*"), ("BRAIN_LOCAL_MODEL", "*"))

CREDENTIAL_NAME = r"(?i)(TOKEN|PASSW|SECRET|KEY|CREDENTIAL|PRIVATE)"
