"""Device adapters. Each adapter is one module, has no import-time side effects, and is constructed as
`Adapter(name, options, settings)`; the object implements the ports for the capabilities it is given.

Only the composition root (`leafi/app.py`) uses this registry; tracks never import adapters (ADR-0002).
"""

from __future__ import annotations

import importlib

ADAPTERS: dict[str, str] = {
    "console": "leafi.devices.console:ConsoleDevice",
    "notifier": "leafi.devices.notifiers:NotifierDevice",
    "go2rtc_camera": "leafi.devices.go2rtc_camera:Go2rtcCamera",
    "local_pc": "leafi.devices.local_pc:LocalPcDevice",
    "panel": "leafi.devices.panel:PanelDevice",  # `study --panel` (session panel design D1)
}


def factory(adapter: str) -> type:
    try:
        target = ADAPTERS[adapter]
    except KeyError:
        raise LookupError(f"unknown adapter {adapter!r}") from None
    module, _, attr = target.partition(":")
    return getattr(importlib.import_module(module), attr)
