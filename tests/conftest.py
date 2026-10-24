"""Shared fixtures. Hardware/model tests are skipped unless LEAFI_HW_TESTS=1."""

from __future__ import annotations

import pytest

from leafi.core.config import Settings, hardware_tests_enabled


@pytest.fixture(autouse=True, scope="session")
def _bootstrap():
    """Every Leafi process starts through `leafi.bootstrap`; the suite does too, enforcing (M5 design D2), so a
    test that sends anything unmediated to a cloud address fails instead of reaching it."""
    from leafi import bootstrap

    bootstrap.install(Settings(_env_file=None, devices_file="does-not-exist.yml"), mode="enforce")
    yield


@pytest.fixture(autouse=True)
def _offline_egress(monkeypatch):
    """The process's Egress in a test puts nothing on the wire: its transport raises a connect error. A test that
    needs a server installs its own Egress (`runtime.use`) with a loopback destination or an `inner` transport."""
    import httpx2

    from leafi.privacy import egress, runtime

    class Offline(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx2.ConnectError("tests never reach the network")

    async def test_net(host, port, ttl):  # no DNS lookup leaves the machine either
        return ["192.0.2.1"]

    def get(settings):
        if runtime._egress is None:
            runtime.use(egress.Egress(settings, env_file=None, inner=Offline(), resolve=test_net))
        return runtime._egress

    monkeypatch.setattr(runtime, "get", get)
    yield
    runtime.use(None)


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
        page_diff_threshold=1.0,  # PIL-rendered pages differ by ~1.7; the desk camera default is 6.0 (P-3)
    )
