"""Where egress may send (M5 design D4): one frozen record per destination; a host no destination lists is refused.

Each record names the purposes it accepts, its locality (`cloud` filters learner text, `local` and `lan` do not),
the request headers it accepts (exact values for those that carry meaning, a pattern for the SDK's own, any value
for the credential), and its redirect policy (study purposes never follow one; `ops` downloads follow only to the
hosts listed, D16). URL-configured destinations are built from the settings.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from leafi.core.config import Settings

STUDY = frozenset({"decide", "generate", "answer", "judge", "word", "tts", "media", "catalog", "notify"})
OPS = "ops"
TEXT_PURPOSES = STUDY - {"media"}  # one mediator retry (D7)

ANY = re.compile(r".*", re.DOTALL)  # a credential: its value is the owner's, never learner text
_TOKENISH = re.compile(r"[A-Za-z0-9 ._:/+(),;=*-]{0,80}")  # protocol and SDK telemetry headers: no free text

# Headers every httpx2 request carries; the transport adds content-length itself.
BASE_HEADERS: Mapping[str, object] = {
    "host": ANY, "accept": _TOKENISH, "accept-encoding": _TOKENISH, "connection": _TOKENISH,
    "content-length": re.compile(r"\d+"), "content-type": re.compile(r"application/(json|x-www-form-urlencoded)"),
    "user-agent": _TOKENISH,
}
ANTHROPIC_HEADERS: Mapping[str, object] = {
    **BASE_HEADERS, "x-api-key": ANY, "anthropic-version": "2023-06-01", "anthropic-beta": _TOKENISH,
    **{f"x-stainless-{k}": _TOKENISH for k in ("timeout", "retry-count", "read-timeout", "lang", "package-version",
                                               "os", "arch", "runtime", "runtime-version", "async")},
}


@dataclass(frozen=True)
class Redirects:
    hosts: frozenset[str] = frozenset()  # hosts a hop may go to (besides the destination's own)
    max_hops: int = 5


@dataclass(frozen=True)
class Destination:
    name: str
    scheme: str
    hosts: frozenset[str]
    port: int
    purposes: frozenset[str]
    locality: str  # "cloud" | "local" | "lan"
    headers: Mapping[str, object] = field(default_factory=lambda: dict(BASE_HEADERS))
    redirects: Redirects | None = None  # None: a 3xx is refused

    def accepts_header(self, name: str, value: str) -> bool:
        rule = self.headers.get(name.lower())
        if rule is None:
            return False
        if isinstance(rule, str):
            return value == rule
        return bool(rule.fullmatch(value))


def _from_url(name: str, url: str, purposes: frozenset[str], locality: str, **kw) -> Destination | None:
    if not url:
        return None
    u = urlsplit(url)
    if not u.hostname:
        return None
    port = u.port or (443 if u.scheme == "https" else 80)
    return Destination(name, u.scheme, frozenset({u.hostname.lower()}), port, purposes, locality, **kw)


def registry(settings: Settings) -> dict[str, Destination]:
    """The destinations this install may reach, from its settings."""
    https = 443
    out: list[Destination | None] = [
        Destination("anthropic", "https", frozenset({"api.anthropic.com"}), https,
                    frozenset({"decide", "generate", "answer", "judge", "word"}), "cloud", ANTHROPIC_HEADERS),
        Destination("edge_tts", "wss", frozenset({"speech.platform.bing.com"}), https, frozenset({"tts"}), "cloud"),
        Destination("telegram", "https", frozenset({"api.telegram.org"}), https, frozenset({"notify", OPS}), "cloud"),
        Destination("openlibrary", "https", frozenset({"openlibrary.org", "covers.openlibrary.org"}), https,
                    frozenset({"catalog"}), "cloud"),
        _from_url("bark", settings.bark_url, frozenset({"notify"}), "cloud"),
        _from_url("healthchecks", settings.heartbeat_url, frozenset({OPS}), "cloud"),
        _from_url("gatus", settings.gatus_url, frozenset({OPS}), "local"),
        _from_url("ollama", settings.ollama_url, frozenset({"decide", "generate", "answer", "judge", "word"}),
                  "local"),
        _from_url("ollama_probe", settings.ollama_url, frozenset({OPS}), "local"),
        _from_url("magpie", getattr(settings, "magpie_url", ""),
                  frozenset({"decide", "generate", "answer", "judge", "word"}), "cloud"),
        Destination("github", "https", frozenset({"github.com"}), https, frozenset({OPS}), "cloud",
                    redirects=Redirects(frozenset({"release-assets.githubusercontent.com",
                                                   "objects.githubusercontent.com"}))),
        Destination("raw_github", "https", frozenset({"raw.githubusercontent.com"}), https, frozenset({OPS}), "cloud"),
        Destination("osf", "https", frozenset({"osf.io"}), https, frozenset({OPS}), "cloud",
                    redirects=Redirects(frozenset({"files.osf.io", "files.de-1.osf.io", "files.us.osf.io"}))),
        Destination("cambridge", "https", frozenset({"www.cambridgeenglish.org"}), https, frozenset({OPS}), "cloud"),
        Destination("openslr", "https", frozenset({"www.openslr.org", "openslr.elda.org", "us.openslr.org"}), https,
                    frozenset({OPS}), "cloud",
                    redirects=Redirects(frozenset({"openslr.elda.org", "us.openslr.org", "openslr.magicdatatech.com"}))),
        Destination("huggingface", "https", frozenset({"huggingface.co"}), https, frozenset({OPS}), "cloud",
                    redirects=Redirects(frozenset({"cdn-lfs.huggingface.co", "cdn-lfs-us-1.hf.co",
                                                   "cas-bridge.xethub.hf.co"}))),
    ]
    return {d.name: d for d in out if d is not None}


def find(reg: Mapping[str, Destination], host: str, port: int) -> Destination | None:
    """The destination owning (host, port), for diagnostics; egress itself always names its destination."""
    for d in reg.values():
        if host.lower() in d.hosts and d.port == port:
            return d
    return None
