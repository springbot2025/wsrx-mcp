"""FastMCP server exposing wsrx tunnel management as MCP tools."""

from __future__ import annotations

import os
import atexit

from mcp.server.fastmcp import FastMCP

from .manager import (
    DEFAULT_BINARY,
    DEFAULT_BIND_HOST,
    DEFAULT_STARTUP_TIMEOUT,
    TunnelManager,
)

__all__ = ["mcp", "main"]


def _build_manager() -> TunnelManager:
    return TunnelManager(
        binary=os.getenv("WSRX_BINARY", DEFAULT_BINARY),
        bind_host=os.getenv("WSRX_MCP_BIND_HOST", DEFAULT_BIND_HOST),
        startup_timeout=float(os.getenv("WSRX_MCP_STARTUP_TIMEOUT", DEFAULT_STARTUP_TIMEOUT)),
    )


manager = _build_manager()
atexit.register(manager.stop_all)

mcp = FastMCP(
    "wsrx",
    instructions=(
        "Manage WebSocket Reflector X (wsrx) tunnels. A tunnel forwards a "
        "local TCP port to a remote ws:// or wss:// URL, so ordinary TCP "
        "tools (netcat, pwntools, curl, browsers) can reach endpoints that "
        "are only exposed over WebSocket - e.g. CTF platforms that publish "
        "instance traffic links like wss://host/api/traffic/<token>?port=N."
    ),
)


@mcp.tool()
def wsrx_connect(remote: str, local_port: int | None = None, wait: bool = True) -> dict:
    """Forward a local TCP port to a remote ws:// or wss:// URL via wsrx.

    Spawns one ``wsrx connect`` subprocess and returns the local endpoint to
    connect TCP clients to. Idempotent: if a live tunnel for the same remote
    already exists it is reused. When ``local_port`` is omitted a free port
    is chosen automatically. When ``wait`` is true the call blocks until the
    local port accepts TCP connections (default 15s timeout).
    """
    return manager.connect(remote, local_port=local_port, wait=wait)


@mcp.tool()
def wsrx_list() -> list[dict]:
    """List all wsrx tunnels with their endpoints and aliveness."""
    return manager.list()


@mcp.tool()
def wsrx_disconnect(local_port: int | None = None, remote: str | None = None) -> dict:
    """Close one wsrx tunnel identified by its local port or remote URL.

    Pass exactly one of ``local_port`` / ``remote``. Returns
    ``{"stopped": true|false}`` plus the removed tunnel's info when found.
    """
    return manager.disconnect(local_port=local_port, remote=remote)


@mcp.tool()
def wsrx_stop_all() -> dict:
    """Close every wsrx tunnel this server owns."""
    count = manager.stop_all()
    return {"stopped": count}


@mcp.tool()
def wsrx_doctor() -> dict:
    """Check whether the wsrx binary is available and list current tunnels."""
    return manager.doctor()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
