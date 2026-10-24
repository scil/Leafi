"""The Brain's tiers from the settings (M7 design D9, D10): each `backend:model` entry of `brain_tiers()` becomes a
backend on the port. Called by the composition root; the harness never imports a backend.

`ollama:` entries are gated until Ollama is measured beside the other models (research D10; `GATE_FLOOR`), so they
are skipped with a log line even if a hand-edited `.env` holds one; unknown backends likewise.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger("leafi.brain.tiers")


def build(settings, egress=None, *, mock_replies: dict | None = None
          ) -> tuple[dict[str, list[tuple[object, str]]], Callable[[object, str], str]]:
    """(tier -> [(backend, model)], locality(backend, model) -> "cloud" | "local")."""
    from leafi.privacy import destinations as dests
    from leafi.services.brain.claude import ClaudeBrain
    from leafi.services.brain.mock import MockModel

    tiers: dict[str, list[tuple[object, str]]] = {}
    for tier, entries in settings.brain_tiers().items():
        built = []
        for entry in entries:
            backend, _, model = entry.partition(":")
            if not model:
                log.warning("brain tier %s: %r is not backend:model; skipped", tier, entry)
            elif backend == "claude":
                built.append((ClaudeBrain(settings, egress=egress, model=model), model))
            elif backend == "mock":
                built.append((MockModel(mock_replies, name=f"mock:{model}"), model))
            elif backend == "ollama":
                log.warning("brain tier %s: %s is gated until Ollama is measured (research D10); skipped", tier, entry)
            else:
                log.warning("brain tier %s: unknown backend %r; skipped", tier, backend)
        tiers[tier] = built

    def locality(backend, model: str) -> str:
        if getattr(backend, "locality_destination", None) == "mock":
            return "local"
        reg = egress.registry if egress is not None else dests.registry(settings)
        dest = reg.get(getattr(backend, "locality_destination", ""))
        return dests.effective(dest, model, settings) if dest is not None else "cloud"

    return tiers, locality
