# wsrx-mcp

English | [简体中文](README.zh-CN.md)

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that manages [WebSocket Reflector X (wsrx)](https://github.com/XDSEC/websocket-reflector-x) tunnels.

The [ret2shell](https://github.com/ret2shell/ret2shell) CTF platform exposes dynamic challenge instances only through WebSocket traffic links such as:

```
wss://ctf.example.com/api/traffic/<token>?port=9999
```

Unlike platforms that hand out plain `host:port` pairs, you cannot `nc` or `pwntools` into these directly. **wsrx** bridges a WebSocket endpoint to a local TCP port; **wsrx-mcp** lets your MCP client (Claude Desktop, ZCode, or any other MCP host) start, inspect, and tear down those bridges as tools — no manual terminal work.

```
┌────────────┐   TCP    ┌─────────────┐   WSS    ┌──────────────────┐
│ nc / pwntools├────────►│ wsrx connect├─────────►│ platform instance│
└────────────┘ :1337    └─────────────┘ wss link └──────────────────┘
                     managed by wsrx-mcp (MCP tools)
```

## Tools

| Tool | Description |
|---|---|
| `wsrx_connect(remote, local_port?, wait?)` | Forward a local TCP port to a `ws://`/`wss://` URL. Idempotent per remote; auto-picks a free port; waits until the port accepts TCP. |
| `wsrx_list()` | List tunnels: remote, local port, endpoint, PID, alive. |
| `wsrx_disconnect(local_port? \| remote?)` | Close one tunnel by port or remote URL. |
| `wsrx_stop_all()` | Close every tunnel. |
| `wsrx_doctor()` | Check the wsrx binary is on PATH and list current tunnels. |

## Requirements

- Python ≥ 3.10
- The `wsrx` CLI on PATH ([releases](https://github.com/XDSEC/websocket-reflector-x/releases)), or set `WSRX_BINARY` to its location.

## Install & configure

Run directly from GitHub with `uvx` (recommended — no clone needed):

```json
{
  "mcpServers": {
    "wsrx": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/springbot2025/wsrx-mcp", "wsrx-mcp"]
    }
  }
}
```

Or install once, then point your MCP client at the `wsrx-mcp` command:

```bash
pipx install git+https://github.com/springbot2025/wsrx-mcp
```

```json
{
  "mcpServers": {
    "wsrx": { "command": "wsrx-mcp" }
  }
}
```

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `WSRX_BINARY` | `wsrx` | Path/resolved name of the wsrx executable. |
| `WSRX_MCP_BIND_HOST` | `127.0.0.1` | Address tunnels bind to. Use `0.0.0.0` only if other hosts must reach the tunnels. |
| `WSRX_MCP_STARTUP_TIMEOUT` | `15` | Seconds to wait for a tunnel port to become reachable. |

## Example session

Ask your agent:

> Connect to wss://ctf.example.com/api/traffic/abc123?port=9999 and tell me the local endpoint.

The agent calls `wsrx_connect`, gets back `{"endpoint": "127.0.0.1:54321", ...}`, and can then run `nc 127.0.0.1 54321` or point pwntools at it. Tunnels are reused across calls and shut down when the server exits.

## Security notes

- Tunnels bind to `127.0.0.1` by default.
- The server manages subprocesses and holds no credentials — traffic tokens live in the URLs you pass in.
- Only `ws://` and `wss://` remotes are accepted.

## Development

```bash
pip install -e . pytest
pytest
```

The tunnel core (`wsrx_mcp.manager`) has no MCP dependency and is fully injectable for testing.

## License

MIT
