"""The socket guard (ADR-0018 §2, M5 design D2/D3): the backstop under `leafi.privacy.egress`.

Every connect, datagram send and name resolution in the process is decided here:

1. `LEAFI_NO_NETWORK` (`Policy.no_network`): anything but loopback, and every gateway port, is refused — grants and
   `lan` included. Always raises, whatever the mode (the ADR-0011 tests).
2. A gateway port (the local model servers that receive study payloads: Ollama, magpie) on a loopback or local
   interface address needs a grant.
3. Any other loopback port passes.
4. A `lan` entry, `(private address, port)` of a household device, passes.
5. Anything else needs a live grant whose addresses contain the address and whose port matches.

A grant is an id in a `ContextVar` plus an entry in a shared active set; the guard honours the id only while it is
in the set, so a task or thread that copied the context loses the grant when it is revoked. Every socket admitted
under a grant is recorded (and followed into TLS); revocation shuts each still-open one down (`SHUT_RDWR` only:
closing stays with its owner, never underneath an event loop). A grant is revoked at its deadline at the latest.

Mode `log` (M5a) logs what it would refuse and lets it through; `enforce` raises `NetworkDenied`. On Windows
asyncio the audit hook does not see the proactor's `ConnectEx`, so the `sock_connect` patch is the only check
there. Sockets opened by subprocesses are not seen at all.
"""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import itertools
import logging
import socket
import ssl
import sys
import threading
import time
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger("leafi.netguard")

_installed = False
_install_lock = threading.Lock()


class NetworkDenied(OSError):
    pass


@dataclass(frozen=True)
class Policy:
    mode: str = "log"  # "log" | "enforce"
    no_network: bool = False
    gateway_ports: frozenset[int] = frozenset()
    lan: frozenset[tuple[str, int]] = frozenset()
    lan_names: frozenset[str] = frozenset()  # host names whose resolution is allowed (lan devices)
    local_addresses: frozenset[str] = frozenset()  # this machine's interface addresses


_NO_NETWORK = Policy(mode="enforce", no_network=True)
_policy: Policy = Policy(mode="log")


@dataclass(eq=False)
class Grant:
    host: str
    addresses: frozenset[str]
    port: int | None  # None: a resolution grant (no connect)
    expires: float  # time.monotonic()
    kind: str = "connect"  # "connect" | "resolve"
    id: int = field(default_factory=lambda: next(_ids))
    sockets: weakref.WeakSet = field(default_factory=weakref.WeakSet)
    _timer: threading.Timer | None = None


_ids = itertools.count(1)
_active: dict[int, Grant] = {}
_active_lock = threading.Lock()
_current: contextvars.ContextVar[tuple[int, ...]] = contextvars.ContextVar("leafi_grants", default=())
_socket_grant: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # socket → grant id


# ---------------------------------------------------------------- grants


def live_grants() -> list[Grant]:
    """Grants this context holds that are still active and not expired."""
    now = time.monotonic()
    with _active_lock:
        return [g for i in _current.get() if (g := _active.get(i)) is not None and g.expires > now]


@contextmanager
def grant(host: str, addresses: list[str] | frozenset[str], port: int | None, *, ttl_s: float,
          kind: str = "connect") -> Iterator[Grant]:
    """Open a grant for this context (and contexts copied from it while it lives); revoked on exit or at `ttl_s`."""
    g, token = open_grant(host, addresses, port, ttl_s=ttl_s, kind=kind)
    try:
        yield g
    finally:
        leave(token)
        revoke(g)


def open_grant(host: str, addresses: list[str] | frozenset[str], port: int | None, *, ttl_s: float,
               kind: str = "connect") -> tuple[Grant, contextvars.Token]:
    """The parts of `grant` for a caller whose grant outlives the code that opened it (a response stream): it
    leaves the context with `leave(token)` once connected, and revokes with `revoke(g)` when the stream ends."""
    g = Grant(host.lower(), frozenset(_norm(a) for a in addresses), port, time.monotonic() + ttl_s, kind)
    with _active_lock:
        _active[g.id] = g
    g._timer = threading.Timer(ttl_s, revoke, args=(g,))
    g._timer.daemon = True
    g._timer.start()
    return g, _current.set(_current.get() + (g.id,))


def leave(token: contextvars.Token) -> None:
    _current.reset(token)


def revoke(g: Grant) -> None:
    """Remove the grant and shut down every socket admitted under it that is still open (idempotent)."""
    with _active_lock:
        _active.pop(g.id, None)
        socks = list(g.sockets)
    if g._timer is not None:
        g._timer.cancel()
    for s in socks:
        try:
            if s.fileno() != -1:
                s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _admit(sock: object, g: Grant | None) -> None:
    if g is None or sock is None:
        return
    try:
        g.sockets.add(sock)
        _socket_grant[sock] = g.id
    except TypeError:  # not weak-referenceable (a wrapper we do not own); the grant's deadline still applies
        pass


# ---------------------------------------------------------------- decisions


def _norm(host: object) -> str:
    h = host.decode() if isinstance(host, bytes) else str(host)
    return h.split("%")[0].lower()


def _ip(h: str):
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return None


def _is_loopback(host: object) -> bool:
    if host is None:
        return True
    h = _norm(host)
    if h in ("localhost", ""):
        return True
    ip = _ip(h)
    if ip is not None:
        return ip.is_loopback
    return h.endswith(".localhost")


def is_private(address: str) -> bool:
    ip = _ip(_norm(address))
    return ip is not None and (ip.is_private or ip.is_link_local) and not ip.is_loopback


def decide(host: object, port: int | None) -> tuple[Grant | None, str | None]:
    """(the grant that admits it, None) or (None, the reason it is refused); (None, None) when no grant is needed."""
    p = _policy
    h = _norm(host) if host is not None else ""
    loop_ = _is_loopback(host)
    local = loop_ or h in p.local_addresses or h in ("0.0.0.0", "::")
    gateway = port is not None and port in p.gateway_ports and local
    if p.no_network and (not loop_ or gateway):
        return None, f"LEAFI_NO_NETWORK: connect to {h or host!r}:{port} denied"
    if loop_ and not gateway:
        return None, None
    if not gateway and port is not None and (h, port) in p.lan:
        return None, None
    for g in live_grants():
        if g.kind == "connect" and (h in g.addresses or h == g.host) and (g.port is None or g.port == port):
            return g, None
    what = "gateway port" if gateway else "address"
    return None, f"no grant for {what} {h or host!r}:{port}"


def _refuse(reason: str) -> None:
    if _policy.mode == "enforce" or reason.startswith("LEAFI_NO_NETWORK"):
        raise NetworkDenied(reason)
    log.warning("netguard (log-only) would refuse: %s", reason)


def check(host: object, port: int | None, sock: object = None) -> None:
    g, reason = decide(host, port)
    if reason is not None:
        _refuse(reason)
        return
    _admit(sock, g)


def _check_address(address: object, sock: object = None) -> None:
    if isinstance(address, tuple) and address:
        check(address[0], address[1] if len(address) > 1 else None, sock)


def _resolution(host: object) -> tuple[str, Grant | None, str | None]:
    """("pass" | "answer" | "refuse", the grant whose addresses answer it, the refusal reason)."""
    if host is None or _is_loopback(host) or _ip(_norm(host)) is not None:
        return "pass", None, None  # literals are decided at connect
    h = _norm(host)
    p = _policy
    if p.no_network:
        return "refuse", None, f"LEAFI_NO_NETWORK: resolve {h!r} denied"
    if h in p.lan_names:
        return "pass", None, None
    for g in live_grants():
        if g.host == h:
            return ("pass", g, None) if g.kind == "resolve" or not g.addresses else ("answer", g, None)
    return "refuse", None, f"no grant to resolve {h!r}"


def _answer(g: Grant, port: object, family: int, type_: int, proto: int) -> list:
    out = []
    for a in sorted(g.addresses):
        ip = ipaddress.ip_address(a)
        fam = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        if family not in (0, socket.AF_UNSPEC, fam):
            continue
        if port in (None, ""):
            p = 0
        elif isinstance(port, int) or str(port).isdigit():
            p = int(port)
        else:
            p = socket.getservbyname(port.decode() if isinstance(port, bytes) else str(port))
        sa = (a, p, 0, 0) if fam == socket.AF_INET6 else (a, p)
        out.append((fam, type_ or socket.SOCK_STREAM, proto or socket.IPPROTO_TCP, "", sa))
    return out


# ---------------------------------------------------------------- install


def configure(policy: Policy) -> None:
    """Replace the policy (bootstrap at start; tests); installs the patches on first use."""
    global _policy
    _policy = policy
    _install_patches()


def install(policy: Policy | None = None) -> None:
    """Without a policy: the ADR-0011 behaviour, every non-loopback connect refused (`LEAFI_NO_NETWORK`)."""
    configure(_NO_NETWORK if policy is None else policy)


def policy() -> Policy:
    return _policy


def _install_patches() -> None:
    global _installed
    with _install_lock:
        if _installed:
            return
        _installed = True

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_sendto = socket.socket.sendto
    orig_sendmsg = getattr(socket.socket, "sendmsg", None)
    orig_getaddrinfo = socket.getaddrinfo
    orig_wrap = ssl.SSLContext.wrap_socket

    def connect(self, address):
        _check_address(address, self)
        with _checked():
            return orig_connect(self, address)

    def connect_ex(self, address):
        _check_address(address, self)
        with _checked():
            return orig_connect_ex(self, address)

    def sendto(self, data, *args):
        _check_address(args[-1], self)
        with _checked():
            return orig_sendto(self, data, *args)

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        what, g, reason = _resolution(host)
        if what == "answer":
            return _answer(g, port, family, type, proto)
        if what == "refuse":
            _refuse(reason)
        return orig_getaddrinfo(host, port, family, type, proto, flags)

    def wrap_socket(self, sock, *args, **kwargs):
        wrapped = orig_wrap(self, sock, *args, **kwargs)
        gid = _socket_grant.get(sock)  # wrapping detaches `sock` (fd -1): membership moves to the TLS socket
        if gid is not None:
            with _active_lock:
                g = _active.get(gid)
            _admit(wrapped, g)
        return wrapped

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    if orig_sendmsg is not None:
        def sendmsg(self, buffers, ancdata=(), flags=0, address=None):
            if address is not None:
                _check_address(address, self)
                with _checked():
                    return orig_sendmsg(self, buffers, ancdata, flags, address)
            return orig_sendmsg(self, buffers, ancdata, flags)

        socket.socket.sendmsg = sendmsg
    socket.getaddrinfo = getaddrinfo
    ssl.SSLContext.wrap_socket = wrap_socket

    base = asyncio.base_events.BaseEventLoop
    orig_create_connection = base.create_connection
    orig_create_datagram = base.create_datagram_endpoint

    async def create_connection(self, protocol_factory, host=None, port=None, *args, **kwargs):
        sock = kwargs.get("sock")
        if sock is not None:  # an already-connected socket: decide on its peer
            try:
                peer = sock.getpeername()
            except OSError:
                peer = None
            if peer:
                _check_address(peer, sock)
        elif host is not None and _ip(_norm(host)) is not None:
            check(host, port)  # a literal: sock_connect records the socket
        return await orig_create_connection(self, protocol_factory, host, port, *args, **kwargs)

    async def create_datagram_endpoint(self, protocol_factory, local_addr=None, remote_addr=None, **kwargs):
        if remote_addr is not None:
            what, _, reason = _resolution(remote_addr[0])
            if what == "refuse":
                _refuse(reason)
            elif _ip(_norm(remote_addr[0])) is not None or _is_loopback(remote_addr[0]):
                check(remote_addr[0], remote_addr[1])
        return await orig_create_datagram(self, protocol_factory, local_addr, remote_addr, **kwargs)

    async def loop_getaddrinfo(self, host, port, *, family=0, type=0, proto=0, flags=0):
        what, g, reason = _resolution(host)  # decided in the caller's context, not the executor's
        if what == "answer":
            return _answer(g, port, family, type, proto)
        if what == "refuse":
            _refuse(reason)
        ctx = contextvars.copy_context()
        return await self.run_in_executor(None, lambda: ctx.run(orig_getaddrinfo, host, port, family, type, proto,
                                                                flags))

    base.create_connection = create_connection
    base.create_datagram_endpoint = create_datagram_endpoint
    base.getaddrinfo = loop_getaddrinfo

    for cls in _loop_classes():
        orig = cls.sock_connect

        async def sock_connect(self, sock, address, _orig=orig):
            _check_address(address, sock)
            return await _orig(self, sock, address)

        cls.sock_connect = sock_connect

    sys.addaudithook(_audit)


_in_audit = threading.local()


@contextmanager
def _checked() -> Iterator[None]:
    """A patched call already decided this operation: its audit event is not decided twice."""
    prev = getattr(_in_audit, "on", False)
    _in_audit.on = True
    try:
        yield
    finally:
        _in_audit.on = prev


def _audit(event: str, args: tuple) -> None:
    """The backstop for paths the patches miss (C extensions calling the socket module's C API go through the same
    audit events). A refusal raises only in enforce mode or under LEAFI_NO_NETWORK."""
    if event not in ("socket.connect", "socket.sendto") or getattr(_in_audit, "on", False):
        return
    _in_audit.on = True
    try:
        sock, address = args[0], args[1]
        if isinstance(address, tuple) and address and _socket_grant.get(sock) is None:
            g, reason = decide(address[0], address[1] if len(address) > 1 else None)
            if reason is not None:
                _refuse(reason)
    finally:
        _in_audit.on = False


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
