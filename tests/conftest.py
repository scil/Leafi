"""Shared fixtures. Hardware/model tests are skipped unless LEAFI_HW_TESTS=1."""

from __future__ import annotations

import pytest

from leafi.core.config import Settings, hardware_tests_enabled


def pytest_collection_modifyitems(config, items):
    if hardware_tests_enabled():
        return
    skip = pytest.mark.skip(reason="hardware/model test; set LEAFI_HW_TESTS=1")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    """Settings isolated from .env and the shell: temp data/cache, mock backends, no API key."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        models_dir=tmp_path / "models",
        tts_backend_en="mock",
        tts_backend_zh="mock",
        ocr_backend="mock",
        asr_backend="mock",
        pron_backend="mock",
        brain_backend="mock",
        anthropic_api_key="",
        anki_url="http://127.0.0.1:8765",
    )
