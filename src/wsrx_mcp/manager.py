"""Process management for ``wsrx connect`` tunnels.

This module has no dependency on the MCP SDK so it can be tested (and
reused) standalone.  One ``wsrx connect`` subprocess bridges one remote
``ws://``/``wss://`` URL to one local TCP port; the manager keeps those
subprocesses alive, probes readiness, and tears them down on demand or at
interpreter exit.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

DEFAULT_BINARY = "wsrx"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_STARTUP_TIMEOUT = 15.0
DEFAULT_STARTUP_INTERVAL = 0.3
DEFAULT_CONNECT_TIMEOUT = 1.0
TERMINATE_TIMEOUT = 5.0

VALID_SCHEMES = ("ws", "wss")


def validate_remote(remote: str) -> str:
    """Reject anything that is not a ``ws://`` or ``wss://`` URL."""

    parsed = urlparse(remote)
    if parsed.scheme not in VALID_SCHEMES or not parsed.netloc:
        raise ValueError(f"remote must be a ws:// or wss:// URL, got {remote!r}")
    return remote


def find_free_port(host: str = "127.0.0.1") -> int:
    """Ask the OS for a currently free TCP port (best effort)."""

    with socket.socket() as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@dataclass
class Tunnel:
    remote: str
    local_port: int
    bind_host: str
    process: Any
    created_at: float = field(default_factory=time.time)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def connect_host(self) -> str:
        # A wildcard bind is reachable from localhost via loopback.
        if self.bind_host in ("0.0.0.0", "::", ""):
            return "127.0.0.1"
        return self.bind_host

    @property
    def endpoint(self) -> str:
        return f"{self.connect_host}:{self.local_port}"


def tunnel_info(tunnel: Tunnel, *, started: bool | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "remote": tunnel.remote,
        "local_port": tunnel.local_port,
        "connect_host": tunnel.connect_host,
        "endpoint": tunnel.endpoint,
        "pid": tunnel.process.pid,
        "alive": tunnel.alive,
        "created_at": tunnel.created_at,
    }
    if started is not None:
        info["started"] = started
    return info


class TunnelManager:
    """Own ``wsrx connect`` subprocesses, keyed by local port.

    ``connect`` is idempotent per remote: a live tunnel for the same remote
    URL is reused instead of spawning a duplicate.  Spawner/probe/terminator/
    port allocator are injectable so tests run without the wsrx binary.
    """

    def __init__(
        self,
        *,
        binary: str = DEFAULT_BINARY,
        bind_host: str = DEFAULT_BIND_HOST,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        startup_interval: float = DEFAULT_STARTUP_INTERVAL,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        spawner: Callable[[str, int], Any] | None = None,
        probe: Callable[[int], bool] | None = None,
        terminator: Callable[[Any], None] | None = None,
        port_allocator: Callable[[], int] | None = None,
    ) -> None:
        self.binary = binary
        self.bind_host = bind_host
        self.startup_timeout = startup_timeout
        self.startup_interval = startup_interval
        self.connect_timeout = connect_timeout
        self._spawner = spawner or self._spawn_process
        self._probe = probe or self._probe_port
        self._terminator = terminator or self._terminate_process
        self._port_allocator = port_allocator or (lambda: find_free_port(self.bind_host))
        self._lock = threading.RLock()
        self._tunnels: dict[int, Tunnel] = {}

    # ---- default subprocess plumbing ----

    def _spawn_process(self, remote: str, local_port: int) -> Any:
        exe = shutil.which(self.binary)
        if exe is None:
            raise RuntimeError(
                f"wsrx binary {self.binary!r} not found on PATH; "
                "install it from https://github.com/XDSEC/WebSocketReflectorX/releases "
                "or point WSRX_BINARY at the executable"
            )
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(
            [
                exe,
                "connect",
                "--host",
                self.bind_host,
                "--port",
                str(local_port),
                remote,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )

    @staticmethod
    def _probe_port(local_port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=1.0):
                return True
        except OSError:
            return False

    @staticmethod
    def _terminate_process(process: Any) -> None:
        try:
            if os.name != "nt" and hasattr(os, "killpg"):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    process.terminate()
            else:
                process.terminate()
            try:
                process.wait(timeout=TERMINATE_TIMEOUT)
            except Exception:
                process.kill()
                try:
                    process.wait(timeout=TERMINATE_TIMEOUT)
                except Exception:
                    pass
        except Exception:
            pass

    # ---- bookkeeping ----

    def _reap_locked(self) -> None:
        for port in [p for p, t in self._tunnels.items() if not t.alive]:
            self._terminator(self._tunnels.pop(port).process)

    def _wait_ready(self, tunnel: Tunnel) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if not tunnel.alive:
                self._terminator(tunnel.process)
                with self._lock:
                    self._tunnels.pop(tunnel.local_port, None)
                raise RuntimeError(
                    f"wsrx tunnel for {tunnel.remote} exited immediately "
                    f"(code {tunnel.process.returncode}); is wsrx installed?"
                )
            if self._probe(tunnel.local_port):
                return
            time.sleep(self.startup_interval)
        self._terminator(tunnel.process)
        with self._lock:
            self._tunnels.pop(tunnel.local_port, None)
        raise RuntimeError(
            f"wsrx tunnel port {tunnel.local_port} did not become reachable "
            f"within {self.startup_timeout:.0f}s"
        )

    # ---- public API ----

    def connect(
        self, remote: str, *, local_port: int | None = None, wait: bool = True
    ) -> dict[str, Any]:
        """Open (or reuse) a tunnel and return its info dict."""

        validate_remote(remote)
        with self._lock:
            self._reap_locked()
            for tunnel in self._tunnels.values():
                if tunnel.remote == remote and tunnel.alive:
                    return tunnel_info(tunnel, started=False)
            if local_port is None:
                local_port = self._port_allocator()
            if local_port in self._tunnels:
                raise RuntimeError(
                    f"local port {local_port} is already used by a tunnel to "
                    f"{self._tunnels[local_port].remote}"
                )
            process = self._spawner(remote, local_port)
            tunnel = Tunnel(remote, local_port, self.bind_host, process)
            self._tunnels[local_port] = tunnel
        if wait:
            self._wait_ready(tunnel)
        return tunnel_info(tunnel, started=True)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self._reap_locked()
            return [
                tunnel_info(t)
                for t in sorted(self._tunnels.values(), key=lambda t: t.local_port)
            ]

    def disconnect(
        self, *, local_port: int | None = None, remote: str | None = None
    ) -> dict[str, Any]:
        if (local_port is None) == (remote is None):
            raise ValueError("pass exactly one of local_port or remote")
        with self._lock:
            self._reap_locked()
            tunnel: Tunnel | None = None
            if local_port is not None:
                tunnel = self._tunnels.pop(local_port, None)
            else:
                for port, candidate in list(self._tunnels.items()):
                    if candidate.remote == remote:
                        tunnel = candidate
                        del self._tunnels[port]
                        break
            if tunnel is None:
                return {"stopped": False}
            process = tunnel.process
        self._terminator(process)
        return {"stopped": True, **tunnel_info(tunnel)}

    def stop_all(self) -> int:
        with self._lock:
            tunnels = list(self._tunnels.values())
            self._tunnels.clear()
        for tunnel in tunnels:
            self._terminator(tunnel.process)
        return len(tunnels)

    def doctor(self) -> dict[str, Any]:
        """Report whether the wsrx binary is usable and list live tunnels."""

        path = shutil.which(self.binary)
        return {
            "binary": self.binary,
            "binary_path": path,
            "bind_host": self.bind_host,
            "startup_timeout": self.startup_timeout,
            "tunnels": self.list(),
        }
