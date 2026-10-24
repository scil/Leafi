"""The socket guard (ADR-0018 §2, M5 design D2/D3), in the pytest process with real sockets on loopback.

A loopback port marked as a gateway port stands in for a protected destination: it needs a grant, as a cloud
address would, so admission and revocation are tested against a real server without anything leaving the
machine. Refusals of real non-loopback addresses use TEST-NET-1 (192.0.2.0/24) and are raised before any packet.
`tests/tls/localhost.*` is a self-signed test certificate (no secret: it guards nothing), for the retained-TLS-socket case.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import socket
import ssl
import threading
from pathlib import Path

import pytest

from leafi import bootstrap
from leafi.core import netguard
from leafi.core.config import Settings

TLS = Path(__file__).parent / "tls"


@pytest.fixture
def guard():
    """Configure an enforcing policy for one test, then put the suite's back."""
    before = netguard.policy()

    def use(**kw) -> netguard.Policy:
        p = netguard.Policy(**{"mode": "enforce", **kw})
        netguard.configure(p)
        return p

    yield use
    netguard.configure(before)


class Server:
    """A loopback TCP (optionally TLS) server that echoes and holds each connection open until the client goes."""

    def __init__(self, tls: bool = False) -> None:
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.ctx = None
        if tls:
            self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ctx.load_cert_chain(TLS / "localhost.crt", TLS / "localhost.key")
        self._stop = False
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            threading.Thread(target=self._echo, args=(c,), daemon=True).start()

    def _echo(self, c: socket.socket) -> None:
        try:
            if self.ctx is not None:
                c = self.ctx.wrap_socket(c, server_side=True)
            while data := c.recv(1024):
                c.sendall(data)
        except OSError:
            pass
        finally:
            c.close()

    def close(self) -> None:
        self._stop = True
        self.sock.close()


@pytest.fixture
def server():
    s = Server()
    yield s
    s.close()


def _dead(sock) -> bool:
    """A shut-down socket reads EOF or fails at once."""
    sock.settimeout(2)
    try:
        sock.sendall(b"x")
        return sock.recv(1) == b""
    except (OSError, ssl.SSLError):
        return True


# ---------------------------------------------------------------- decisions


def test_decisions(guard):
    guard(gateway_ports=frozenset({11434}), lan=frozenset({("192.168.1.20", 1984)}),
          local_addresses=frozenset({"192.168.1.5"}))
    assert netguard.decide("127.0.0.1", 8765) == (None, None)  # loopback
    assert netguard.decide("192.168.1.20", 1984) == (None, None)  # lan entry
    assert "no grant" in netguard.decide("192.168.1.20", 22)[1]  # lan is (address, port), not a host
    assert "gateway port" in netguard.decide("127.0.0.1", 11434)[1]
    assert "gateway port" in netguard.decide("192.168.1.5", 11434)[1]  # on this machine's LAN address too
    assert "gateway port" in netguard.decide("0.0.0.0", 11434)[1]
    assert "no grant" in netguard.decide("192.0.2.1", 443)[1]
    with netguard.grant("api.example.test", ["192.0.2.1"], 443, ttl_s=5) as g:
        assert netguard.decide("192.0.2.1", 443) == (g, None)
        assert "no grant" in netguard.decide("192.0.2.1", 80)[1]  # the port is part of the grant
        assert "no grant" in netguard.decide("192.0.2.2", 443)[1]
    assert "no grant" in netguard.decide("192.0.2.1", 443)[1]  # revoked


def test_no_network_refuses_lan_gateways_and_grants_even_in_log_mode(guard):
    guard(mode="log", no_network=True, gateway_ports=frozenset({11434}), lan=frozenset({("192.168.1.20", 1984)}))
    for host, port in [("192.168.1.20", 1984), ("127.0.0.1", 11434), ("192.0.2.1", 443)]:
        with netguard.grant("x.test", ["192.0.2.1", "127.0.0.1"], port, ttl_s=5):
            with pytest.raises(netguard.NetworkDenied, match="LEAFI_NO_NETWORK"):
                netguard.check(host, port)
    netguard.check("127.0.0.1", 8765)


def test_log_mode_logs_and_lets_through(guard, server, caplog):
    guard(mode="log", gateway_ports=frozenset({server.port}))
    with caplog.at_level(logging.WARNING, logger="leafi.netguard"):
        with socket.create_connection(("127.0.0.1", server.port), timeout=2):
            pass
    assert "would refuse: no grant for gateway port" in caplog.text


# ---------------------------------------------------------------- real sockets


def test_sync_connect_refused_without_grant_and_admitted_with_one(guard, server):
    guard(gateway_ports=frozenset({server.port}))
    with pytest.raises(netguard.NetworkDenied):
        socket.create_connection(("127.0.0.1", server.port), timeout=2)
    with pytest.raises(netguard.NetworkDenied):
        socket.create_connection(("192.0.2.1", 80), timeout=2)
    with netguard.grant("127.0.0.1", ["127.0.0.1"], server.port, ttl_s=5):
        s = socket.create_connection(("127.0.0.1", server.port), timeout=2)
        s.sendall(b"hi")
        assert s.recv(2) == b"hi"
    assert _dead(s)  # revocation shut it down
    s.close()


def test_a_thread_keeping_a_tls_socket_loses_it_at_revocation(guard):
    srv = Server(tls=True)
    try:
        guard(gateway_ports=frozenset({srv.port}))
        ctx = ssl.create_default_context(cafile=str(TLS / "localhost.crt"))
        kept: list = []

        def worker(ctx_vars):
            def body():
                raw = socket.create_connection(("127.0.0.1", srv.port), timeout=2)
                tls = ctx.wrap_socket(raw, server_hostname="localhost")  # detaches `raw`: membership must follow
                tls.sendall(b"hi")
                assert tls.recv(2) == b"hi"
                kept.append(tls)
            ctx_vars.run(body)

        with netguard.grant("127.0.0.1", ["127.0.0.1"], srv.port, ttl_s=5):
            t = threading.Thread(target=worker, args=(contextvars.copy_context(),))
            t.start()
            t.join(5)
        (tls,) = kept
        assert _dead(tls)
        tls.close()
    finally:
        srv.close()


async def test_a_child_task_keeping_a_connection_loses_it_and_cannot_reconnect(guard, server):
    guard(gateway_ports=frozenset({server.port}))
    started, release = asyncio.Event(), asyncio.Event()
    result: dict = {}

    async def child():
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        w.write(b"hi")
        result["echo"] = await r.read(2)
        started.set()
        await release.wait()
        try:
            result["after"] = await asyncio.wait_for(r.read(1), 2)
        except (TimeoutError, OSError) as e:
            result["after"] = e
        try:
            await asyncio.open_connection("127.0.0.1", server.port)
            result["reconnect"] = "allowed"
        except netguard.NetworkDenied:
            result["reconnect"] = "refused"
        w.close()

    with netguard.grant("127.0.0.1", ["127.0.0.1"], server.port, ttl_s=5):
        task = asyncio.create_task(child())  # copies the context, grant included
        await started.wait()
    release.set()
    await task
    assert result["echo"] == b"hi"
    assert result["after"] == b"" or isinstance(result["after"], OSError)
    assert result["reconnect"] == "refused"


async def test_a_grant_expires_on_its_own(guard, server):
    guard(gateway_ports=frozenset({server.port}))
    with netguard.grant("127.0.0.1", ["127.0.0.1"], server.port, ttl_s=0.3):
        r, w = await asyncio.open_connection("127.0.0.1", server.port)
        await asyncio.sleep(0.6)
        assert await asyncio.wait_for(r.read(1), 2) == b""  # shut down at the deadline, inside the `with`
        with pytest.raises(netguard.NetworkDenied):
            await asyncio.open_connection("127.0.0.1", server.port)
        w.close()


async def test_create_connection_with_a_connected_socket_is_decided_on_its_peer(guard, server):
    guard(mode="log")
    raw = socket.create_connection(("127.0.0.1", server.port), timeout=2)
    guard(gateway_ports=frozenset({server.port}))
    raw.setblocking(False)
    with pytest.raises(netguard.NetworkDenied):
        await asyncio.get_running_loop().create_connection(asyncio.Protocol, sock=raw)
    raw.close()


async def test_udp_is_guarded(guard):
    guard()
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with pytest.raises(netguard.NetworkDenied):
        u.sendto(b"x", ("192.0.2.1", 53))
    u.close()
    with pytest.raises(netguard.NetworkDenied):
        await asyncio.get_running_loop().create_datagram_endpoint(asyncio.DatagramProtocol,
                                                                  remote_addr=("192.0.2.1", 53))


async def test_names_resolve_only_inside_a_grant_and_from_its_addresses(guard, server):
    guard(gateway_ports=frozenset({server.port}))
    with pytest.raises(netguard.NetworkDenied):
        socket.getaddrinfo("api.example.test", 443)
    loop = asyncio.get_running_loop()
    with pytest.raises(netguard.NetworkDenied):
        await loop.getaddrinfo("api.example.test", 443)
    with netguard.grant("api.example.test", ["127.0.0.1"], server.port, ttl_s=5):
        got = await loop.getaddrinfo("api.example.test", server.port)
        assert {ai[4] for ai in got} == {("127.0.0.1", server.port)}
        r, w = await asyncio.open_connection("api.example.test", server.port)  # resolves from the grant
        w.write(b"ok")
        assert await r.read(2) == b"ok"
        w.close()


# ---------------------------------------------------------------- bootstrap


def test_bootstrap_policy_from_settings(tmp_path):
    s = Settings(_env_file=None, devices_file=tmp_path / "none.yml", ollama_url="http://127.0.0.1:11434",
                 go2rtc_url="http://192.168.1.20:1984", frigate_url="http://127.0.0.1:15000",
                 gatus_url="https://status.example.test", leafi_no_network=False)
    p = bootstrap.build_policy(s)
    assert p.mode == "enforce" and 11434 in p.gateway_ports
    assert ("192.168.1.20", 1984) in p.lan
    assert not any(port == 443 for _, port in p.lan)  # a public status page is not lan


def test_app_build_refuses_without_bootstrap(settings, monkeypatch):
    from leafi import app

    monkeypatch.setattr(bootstrap, "_installed", None)
    with pytest.raises(RuntimeError, match="bootstrap"):
        app.build(settings, text_mode=True)


def test_the_cli_bootstraps_before_building(tmp_path):
    import subprocess
    import sys

    code = ("import leafi.cli as c, leafi.bootstrap as b; "
            "assert not b.installed(); c._settings(); assert b.installed(); print(b._installed.mode)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path,
                       env={"PYTHONPATH": str(Path.cwd()), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
                       timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    assert r.stdout.strip() == "enforce"


def test_bootstrap_sets_the_offline_environment_and_drops_proxies(tmp_path):
    import subprocess
    import sys

    code = ("import os, leafi.bootstrap as b; from leafi.core.config import Settings; "
            "b.install(Settings(_env_file=None)); "
            "print(os.environ.get('HF_HUB_OFFLINE'), os.environ.get('DO_NOT_TRACK'), 'HTTPS_PROXY' in os.environ)")
    env = {"PYTHONPATH": str(Path.cwd()), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
           "HTTPS_PROXY": "http://proxy.example.test:3128", "HF_HUB_OFFLINE": "0"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, env=env,
                       timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    assert r.stdout.split() == ["1", "1", "False"]


def test_importing_leafi_installs_nothing(tmp_path):
    import subprocess
    import sys

    code = ("import socket, sys, leafi, leafi.core.lease; "
            "assert type(socket.socket.connect).__name__ == 'method_descriptor', socket.socket.connect; "
            "assert 'leafi.core.netguard' not in sys.modules or not sys.modules['leafi.core.netguard']._installed")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path,
                       env={"PYTHONPATH": str(Path.cwd()), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
                       timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
