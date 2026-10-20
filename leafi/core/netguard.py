"""`LEAFI_NO_NETWORK=1`: any connect to a non-loopback address raises `NetworkDenied` (ADR-0011 tests).

Installed once at process start by `leafi.cli` when the setting is on. It patches the sync socket API and
the asyncio connect paths (the Windows proactor loop bypasses `socket.connect`).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

_installed = False


class NetworkDenied(OSError):
    pass


def _is_loopback(host: object) -> bool:
    if host is None:
        return True
    h = host.decode() if isinstance(host, bytes) else str(host)
    if h in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return h.endswith(".localhost")


def _check(address: object) -> None:
    if isinstance(address, tuple) and address:
        if not _is_loopback(address[0]):
            raise NetworkDenied(f"LEAFI_NO_NETWORK: connect to {address[0]!r} denied")


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    def connect(self, address):
        _check(address)
        return orig_connect(self, address)

    def connect_ex(self, address):
        _check(address)
        return orig_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            raise NetworkDenied(f"LEAFI_NO_NETWORK: resolve {host!r} denied")
        return orig_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo

    base = asyncio.base_events.BaseEventLoop
    orig_create_connection = base.create_connection

    async def create_connection(self, protocol_factory, host=None, port=None, *args, **kwargs):
        if not _is_loopback(host):
            raise NetworkDenied(f"LEAFI_NO_NETWORK: connect to {host!r} denied")
        return await orig_create_connection(self, protocol_factory, host, port, *args, **kwargs)

    base.create_connection = create_connection

    for cls in _loop_classes():
        orig = cls.sock_connect

        async def sock_connect(self, sock, address, _orig=orig):
            _check(address)
            return await _orig(self, sock, address)

        cls.sock_connect = sock_connect


def _loop_classes() -> list[type]:
    out: list[type] = [asyncio.base_events.BaseEventLoop]
    try:
        from asyncio import proactor_events

        out.append(proactor_events.BaseProactorEventLoop)
    except ImportError:  # pragma: no cover
        pass
    from asyncio import selector_events

    out.append(selector_events.BaseSelectorEventLoop)
    return out
