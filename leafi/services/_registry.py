"""Backend registry shared by every service package (ADR-0003).

A backend module exposes `create(settings, **kw)` and may expose `status(settings) -> (state, detail)` with
state in {ok, missing package, missing model, disabled, deferred}. Modules are imported only when a
backend is created or its status is asked for, so heavy packages load lazily.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Any


def has_package(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@dataclass
class Registry:
    service: str
    backends: dict[str, str]  # name -> module path
    deferred: set[str] = field(default_factory=set)

    def module(self, name: str):
        if name not in self.backends:
            raise LookupError(f"{self.service}: unknown backend {name!r} (known: {sorted(self.backends)})")
        return importlib.import_module(self.backends[name])

    def create(self, name: str, settings: Any, **kw: Any) -> Any:
        if name in self.deferred:
            raise LookupError(f"{self.service}: backend {name!r} is deferred in v1 (ADR-0011)")
        return self.module(name).create(settings, **kw)

    def status(self, name: str, settings: Any) -> tuple[str, str]:
        if name in self.deferred:
            return "deferred", "port kept; not installed in v1 (ADR-0011)"
        mod = self.module(name)
        fn = getattr(mod, "status", None)
        return fn(settings) if fn else ("ok", "")
