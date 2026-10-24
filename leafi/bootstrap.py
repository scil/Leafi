"""Process start for every Leafi entry point (M5 design D2): installs the socket guard before any service exists.

Called by `leafi.cli` (every `python -m leafi …` command) and by every supported script under `scripts/` that
builds Leafi services; `leafi.app.build()` refuses to run without it, so a forgotten entry point fails at start
instead of running unguarded. Importing `leafi` alone installs nothing, so the habit track (`agent/`, which
imports `leafi.core.lease`) keeps its ADR-0011 behaviour.

Since M5c the guard enforces: every caller sends through `leafi.privacy.egress`, and anything else that tries to
reach a cloud address or a gateway port is refused (`NetworkDenied`). It also sets the third-party environment of
design D15 before any library reads it: Hugging Face and Transformers offline and without telemetry or Xet,
`DO_NOT_TRACK`, Ultralytics' sync off, and no proxy variables (a library honouring `HTTP(S)_PROXY` would send
through a host egress never prepared).
"""

from __future__ import annotations

import logging
import socket
from urllib.parse import urlsplit

from leafi.core import netguard
from leafi.core.config import Settings, env_lookup

log = logging.getLogger("leafi.bootstrap")

MODE = "enforce"

OFFLINE_ENVIRONMENT = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
                       "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_XET": "1", "DO_NOT_TRACK": "1",
                       "YOLO_OFFLINE": "True"}

_installed: netguard.Policy | None = None


def installed() -> bool:
    return _installed is not None


def enforcing() -> bool:
    return _installed is not None and _installed.mode == "enforce"


def install(settings: Settings, *, mode: str = MODE) -> netguard.Policy:
    """Build the policy from the settings and install it; a second call replaces the policy (tests)."""
    global _installed
    from leafi.core.config import clear_proxy_environment, export_for_libraries

    export_for_libraries(OFFLINE_ENVIRONMENT, force=set(OFFLINE_ENVIRONMENT))
    clear_proxy_environment()
    policy = build_policy(settings, mode=mode)
    netguard.configure(policy)
    _installed = policy
    return policy


def _host_port(url: str) -> tuple[str, int] | None:
    if not url:
        return None
    u = urlsplit(url if "//" in url else f"//{url}")
    if not u.hostname:
        return None
    return u.hostname.lower(), u.port or (443 if u.scheme in ("https", "wss") else 80)


def _resolve(host: str) -> set[str]:
    """Resolution at install, before the guard is configured (the household's own names; a DHCP change needs a
    restart)."""
    try:
        return {ai[4][0].split("%")[0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


def _device_urls(settings: Settings) -> list[str]:
    """Every `go2rtc_url` in config/devices.yml; a file that does not parse adds none (`leafi devices` says why)."""
    try:
        from leafi.core.hub import load_devices_config

        cfg = load_devices_config(settings.devices_file, lambda n: env_lookup(n, settings))
    except Exception:  # noqa: BLE001 - the supervisor's devices check reports a broken file
        return []
    return [str(d.options["go2rtc_url"]) for d in cfg.enabled() if d.options.get("go2rtc_url")]


def build_policy(settings: Settings, *, mode: str = MODE) -> netguard.Policy:
    local = {"0.0.0.0", "::"}
    try:
        local |= _resolve(socket.gethostname())
    except OSError:
        pass
    gateway: set[int] = set()
    for url in (settings.ollama_url, getattr(settings, "magpie_url", "")):
        hp = _host_port(url)
        if hp and (netguard._is_loopback(hp[0]) or hp[0] in local or _resolve(hp[0]) & local):
            gateway.add(hp[1])
    lan: set[tuple[str, int]] = set()
    lan_names: set[str] = set()
    urls = [settings.go2rtc_url, settings.frigate_url, settings.gatus_url, *_device_urls(settings)]
    for url in urls:
        hp = _host_port(url)
        if hp is None or netguard._is_loopback(hp[0]):
            continue
        addrs = {a for a in _resolve(hp[0]) if netguard.is_private(a)}
        if not addrs:
            continue  # a public address is not `lan`: an `ops` destination (design D3)
        if hp[1] in gateway and addrs & local:
            continue  # a gateway port wins over a lan entry on the same address
        lan |= {(a, hp[1]) for a in addrs}
        if netguard._ip(hp[0]) is None:
            lan_names.add(hp[0])
    return netguard.Policy(mode=mode, no_network=settings.leafi_no_network, gateway_ports=frozenset(gateway),
                           lan=frozenset(lan), lan_names=frozenset(lan_names),
                           local_addresses=frozenset(a.lower() for a in local))
