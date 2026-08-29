from __future__ import annotations

import pytest

from wsrx_mcp.manager import (
    TunnelManager,
    find_free_port,
    validate_remote,
)


class FakeProcess:
    def __init__(self, pid: int = 1000) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> None:
        return None


def make_manager(**kwargs) -> tuple[TunnelManager, list[str], dict[int, FakeProcess]]:
    """Manager whose probe models reality: a port answers only while the
    process spawned for it is alive."""
    spawned: list[str] = []
    procs: dict[int, FakeProcess] = {}

    def spawner(remote: str, local_port: int) -> FakeProcess:
        spawned.append(remote)
        procs[local_port] = FakeProcess()
        return procs[local_port]

    def probe(local_port: int) -> bool:
        proc = procs.get(local_port)
        return proc is not None and proc.poll() is None

    kwargs.setdefault("spawner", spawner)
    kwargs.setdefault("probe", probe)
    kwargs.setdefault("terminator", lambda proc: proc.terminate())
    kwargs.setdefault("port_allocator", iter([21000, 21001, 21002]).__next__)
    return TunnelManager(**kwargs), spawned, procs


def test_validate_remote():
    assert validate_remote("ws://example.com/x") == "ws://example.com/x"
    assert validate_remote("wss://ctf.example/api/traffic/t?port=1")
    with pytest.raises(ValueError):
        validate_remote("http://example.com")
    with pytest.raises(ValueError):
        validate_remote("ws://")


def test_find_free_port():
    port = find_free_port()
    assert 1024 <= port <= 65535


def test_connect_is_idempotent_per_remote():
    manager, spawned, _ = make_manager()
    first = manager.connect("wss://host/a", local_port=21000)
    second = manager.connect("wss://host/a", local_port=21000)
    assert first["started"] is True
    assert second["started"] is False
    assert spawned == ["wss://host/a"]
    assert second["endpoint"] == "127.0.0.1:21000"


def test_connect_allocates_free_port():
    manager, _, _ = make_manager()
    info = manager.connect("wss://host/a")
    assert info["local_port"] == 21000


def test_distinct_remotes_get_distinct_ports():
    manager, spawned, _ = make_manager()
    one = manager.connect("wss://host/a")
    two = manager.connect("wss://host/b")
    assert one["local_port"] != two["local_port"]
    assert len(spawned) == 2


def test_port_conflict_with_own_tunnel_raises():
    manager, _, _ = make_manager()
    manager.connect("wss://host/a", local_port=21000)
    with pytest.raises(RuntimeError, match="already used by a tunnel"):
        manager.connect("wss://host/c", local_port=21000)


def test_port_occupied_by_foreign_listener_raises():
    manager, spawned, procs = make_manager()
    procs[21000] = FakeProcess()  # someone else listens, no tunnel of ours
    with pytest.raises(RuntimeError, match="in use by another process"):
        manager.connect("wss://host/a", local_port=21000)
    assert spawned == []  # wsrx was never spawned against the stale port


def test_disconnect_by_port():
    manager, _, _ = make_manager()
    info = manager.connect("wss://host/a", local_port=21000)
    result = manager.disconnect(local_port=21000)
    assert result["stopped"] is True
    assert manager.list() == []
    assert result["remote"] == "wss://host/a"
    assert info["alive"] is True


def test_disconnect_by_remote():
    manager, _, _ = make_manager()
    manager.connect("wss://host/a")
    result = manager.disconnect(remote="wss://host/a")
    assert result["stopped"] is True
    assert manager.list() == []


def test_disconnect_requires_exactly_one_selector():
    manager, _, _ = make_manager()
    with pytest.raises(ValueError):
        manager.disconnect()
    with pytest.raises(ValueError):
        manager.disconnect(local_port=1, remote="wss://host/a")


def test_dead_tunnel_is_reaped_and_respawned():
    manager, spawned, _ = make_manager()
    info = manager.connect("wss://host/a", local_port=21000)
    manager._tunnels[21000].process.returncode = 1  # simulate crash
    assert manager.list() == []
    manager.connect("wss://host/a", local_port=21000)
    assert spawned.count("wss://host/a") == 2
    assert info["local_port"] == 21000


def test_wait_ready_failure_cleans_up():
    processes: list[FakeProcess] = []

    manager, spawned, _ = make_manager(
        startup_timeout=0.2,
        startup_interval=0.05,
        probe=lambda port: False,  # port never comes up
        spawner=lambda remote, port: processes.append(FakeProcess()) or processes[-1],
    )
    with pytest.raises(RuntimeError, match="did not become reachable"):
        manager.connect("wss://host/a")
    assert manager.list() == []
    assert processes[0].terminated


def test_instant_exit_raises_and_cleans_up():
    manager, _, _ = make_manager(startup_timeout=0.5, startup_interval=0.05, probe=lambda port: False)

    original = manager._spawner

    def dying_spawner(remote: str, local_port: int):
        proc = original(remote, local_port)
        proc.returncode = 127  # exits immediately, e.g. binary missing
        return proc

    manager._spawner = dying_spawner
    with pytest.raises(RuntimeError, match="exited immediately"):
        manager.connect("wss://host/a")
    assert manager.list() == []


def test_stop_all():
    manager, _, _ = make_manager()
    manager.connect("wss://host/a")
    manager.connect("wss://host/b")
    assert manager.stop_all() == 2
    assert manager.stop_all() == 0
    assert manager.list() == []


def test_doctor_reports_binary():
    manager, _, _ = make_manager()
    report = manager.doctor()
    assert report["bind_host"] == "127.0.0.1"
    assert report["tunnels"] == []
