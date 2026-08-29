# wsrx-mcp

[English](README.md) | 简体中文

一个用于管理 [WebSocket Reflector X（wsrx）](https://github.com/XDSEC/WebSocketReflectorX)隧道的 [MCP（Model Context Protocol）](https://modelcontextprotocol.io)服务。

[ret2shell](https://github.com/ret2shell/ret2shell) CTF 平台的动态靶机只通过 WebSocket 流量链接暴露，形如：

```
wss://ctf.example.com/api/traffic/<token>?port=9999
```

不像直接给出 `host:port` 的平台，这种链接没法直接用 nc / pwntools 连。**wsrx** 负责把 WebSocket 端点桥接成本地 TCP 端口；**wsrx-mcp** 则把"开桥、查桥、拆桥"封装成 MCP 工具，让你的 MCP 客户端（Claude Desktop、ZCode 或任何 MCP 宿主）直接调用，不再需要手动敲终端命令。

```
┌───────────────┐   TCP    ┌──────────────┐   WSS    ┌──────────────────┐
│ nc / pwntools ├─────────►│ wsrx connect ├────────► │     动态靶机     │
└───────────────┘  :1337   └──────────────┘ wss 链接 └──────────────────┘
                      由 wsrx-mcp（MCP 工具）管理
```

## 工具列表

| 工具 | 说明 |
|---|---|
| `wsrx_connect(remote, local_port?, wait?)` | 把本地 TCP 端口转发到 `ws://`/`wss://` 远端。按 remote 幂等复用；未指定端口时自动挑选空闲端口；等待端口可连后返回。 |
| `wsrx_list()` | 列出所有隧道：远端 URL、本地端口、endpoint、PID、存活状态。 |
| `wsrx_disconnect(local_port? \| remote?)` | 按本地端口或远端 URL 关闭一条隧道。 |
| `wsrx_stop_all()` | 关闭本服务器持有的全部隧道。 |
| `wsrx_doctor()` | 检查 wsrx 二进制是否可用，并列出当前隧道。 |

## 环境要求

- Python ≥ 3.10
- PATH 上有 `wsrx` 命令行工具（[releases 下载](https://github.com/XDSEC/WebSocketReflectorX/releases)），或通过 `WSRX_BINARY` 指定其位置。

## 安装与配置

用 `uvx` 直接从 GitHub 运行（推荐，无需克隆仓库）：

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

或者先安装一次，再把 `wsrx-mcp` 命令配到 MCP 客户端里：

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

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WSRX_BINARY` | `wsrx` | wsrx 可执行文件的路径或名称。 |
| `WSRX_MCP_BIND_HOST` | `127.0.0.1` | 隧道绑定地址。仅当其他主机需要访问隧道时才改成 `0.0.0.0`。 |
| `WSRX_MCP_STARTUP_TIMEOUT` | `15` | 等待隧道端口变为可达的秒数。 |

## 使用示例

对 agent 说：

> 连接 wss://ctf.example.com/api/traffic/abc123?port=9999，告诉我本地端口。

agent 调用 `wsrx_connect`，拿到 `{"endpoint": "127.0.0.1:54321", ...}`，接着就能 `nc 127.0.0.1 54321` 或者让 pwntools 连上去。隧道在多次调用间复用，服务器退出时自动关闭。

## 安全说明

- 隧道默认只绑定 `127.0.0.1`。
- 服务器只管理子进程，不保存任何凭据——流量 token 只存在于你传入的 URL 里。
- 仅接受 `ws://` 和 `wss://` 两种远端。

## 本地开发

```bash
pip install -e . pytest
pytest
```

隧道核心（`wsrx_mcp.manager`）不依赖 MCP SDK，全部依赖项可注入，便于测试。

## 许可证

MIT
