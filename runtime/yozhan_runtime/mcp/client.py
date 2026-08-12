"""Model Context Protocol client — stdio transport.

Lets yozhan use tools from any MCP server (filesystem, git, databases, the
growing ecosystem of them) alongside its own skills, so the tool surface isn't
limited to what's been written here.

Implemented directly against the wire protocol rather than pulling in the
official SDK, for one reason: the SDK is async and this runtime is sync
top to bottom. Bridging an event loop into every tool call would add more
moving parts than the protocol itself needs — MCP over stdio is JSON-RPC 2.0
with a handshake, and that is about a hundred lines.

Two transports: stdio for servers you run as a command, and Streamable HTTP
(http_transport.py) for hosted ones, which is where authentication matters —
bearer tokens and the OAuth client_credentials grant are both supported there.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30.0


class MCPError(RuntimeError):
    pass


@dataclass
class MCPTool:
    server: str
    name: str
    description: str
    input_schema: dict

    @property
    def qualified_name(self) -> str:
        """Namespaced so two servers exposing `search` don't collide, and so
        it's obvious in a trace which server a call went to."""
        return f"mcp__{self.server}__{self.name}"

    def as_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": f"[{self.server}] {self.description}",
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"          # "stdio" | "http"
    command: str = ""                 # stdio
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                     # http
    auth: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    enabled: bool = True


class MCPServer:
    """One MCP server subprocess, speaking JSON-RPC over stdin/stdout."""

    def __init__(self, config: MCPServerConfig, timeout: float = DEFAULT_TIMEOUT):
        self.config = config
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._http = None
        self._next_id = 0
        self._lock = threading.Lock()  # one request at a time per server
        self.tools: list[MCPTool] = []

    @property
    def is_http(self) -> bool:
        return self.config.transport == "http"

    # --- process lifecycle ---------------------------------------------------

    def start(self) -> None:
        if self.is_http:
            self._start_http()
            return
        if self._process is not None:
            return
        env = {**os.environ, **self.config.env}
        try:
            self._process = subprocess.Popen(
                [self.config.command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # servers chat on stderr; it isn't protocol
                env=env,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise MCPError(f"MCP server '{self.config.name}': command '{self.config.command}' not found") from exc

        self._handshake()
        self.tools = self._list_tools()

    def _start_http(self) -> None:
        if self._http is not None:
            return
        from yozhan_runtime.mcp.http_transport import HTTPTransport, MCPAuthError, build_auth

        if not self.config.url:
            raise MCPError(f"MCP server '{self.config.name}': transport is http but no url is configured")
        try:
            auth = build_auth(self.config.auth)
        except MCPAuthError as exc:
            raise MCPError(f"MCP server '{self.config.name}': {exc}") from exc

        self._http = HTTPTransport(
            name=self.config.name,
            url=self.config.url,
            auth=auth,
            headers=self.config.headers,
            timeout=self.timeout,
        )
        self._handshake()
        self.tools = self._list_tools()

    def stop(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None
            return
        if self._process is None:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            self._process.kill()
        finally:
            self._process = None

    # --- JSON-RPC ------------------------------------------------------------

    def _send(self, payload: dict) -> None:
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()

    def _read_message(self) -> dict:
        assert self._process is not None and self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            raise MCPError(f"MCP server '{self.config.name}' closed the connection")
        return json.loads(line)

    def _request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}

            if self._http is not None:
                try:
                    message = self._http.request(payload)
                except Exception as exc:
                    raise MCPError(f"{self.config.name}.{method}: {exc}") from exc
                if message is None:
                    raise MCPError(f"MCP server '{self.config.name}' sent no response to {method}")
                if "error" in message:
                    raise MCPError(
                        f"{self.config.name}.{method}: {message['error'].get('message', message['error'])}"
                    )
                return message.get("result", {})

            self._send(payload)

            # Servers may interleave notifications (logging, progress); skip
            # anything that isn't the response we're waiting for.
            for _ in range(100):
                message = self._read_message()
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise MCPError(f"{self.config.name}.{method}: {message['error'].get('message', message['error'])}")
                return message.get("result", {})
            raise MCPError(f"MCP server '{self.config.name}' sent no response to {method}")

    def _notify(self, method: str, params: dict | None = None) -> None:
        with self._lock:
            payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if self._http is not None:
                try:
                    self._http.request(payload)
                except Exception as exc:  # a notification failing is not fatal
                    logger.debug("MCP notification %s to '%s' failed: %s", method, self.config.name, exc)
                return
            self._send(payload)

    def _handshake(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "yozhan", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")

    def _list_tools(self) -> list[MCPTool]:
        result = self._request("tools/list")
        return [
            MCPTool(
                server=self.config.name,
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema") or {},
            )
            for tool in result.get("tools", [])
        ]

    def call(self, tool_name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        return _flatten_content(result)


def _flatten_content(result: dict) -> str:
    """MCP returns a list of typed content blocks; the agent loop wants text."""
    blocks = result.get("content") or []
    parts = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "resource":
            resource = block.get("resource") or {}
            parts.append(resource.get("text") or f"[resource: {resource.get('uri', 'unknown')}]")
        else:
            parts.append(f"[{block.get('type', 'unknown')} content omitted]")
    text = "\n".join(p for p in parts if p)
    if result.get("isError"):
        return f"error: {text or 'the MCP tool reported an error'}"
    return text or "(no output)"


class MCPManager:
    """Starts the configured servers and exposes their tools as one set."""

    def __init__(self, servers: list[MCPServerConfig], timeout: float = DEFAULT_TIMEOUT):
        self.configs = [s for s in servers if s.enabled]
        self.timeout = timeout
        self.servers: dict[str, MCPServer] = {}
        self.errors: dict[str, str] = {}

    def start(self) -> None:
        for config in self.configs:
            server = MCPServer(config, self.timeout)
            try:
                server.start()
                self.servers[config.name] = server
            except Exception as exc:
                # A broken MCP server must not stop yozhan from starting; note
                # it and carry on without its tools.
                logger.warning("MCP server '%s' failed to start: %s", config.name, exc)
                self.errors[config.name] = str(exc)

    def stop(self) -> None:
        for server in self.servers.values():
            server.stop()
        self.servers.clear()

    def tools(self) -> list[MCPTool]:
        return [tool for server in self.servers.values() for tool in server.tools]

    def as_openai_tools(self) -> list[dict]:
        return [tool.as_openai_tool() for tool in self.tools()]

    def handles(self, qualified_name: str) -> bool:
        return qualified_name.startswith("mcp__")

    def call(self, qualified_name: str, arguments: dict) -> str:
        for tool in self.tools():
            if tool.qualified_name == qualified_name:
                try:
                    return self.servers[tool.server].call(tool.name, arguments)
                except MCPError as exc:
                    return f"error: {exc}"
        return f"error: unknown MCP tool '{qualified_name}'"

    def describe(self) -> list[dict]:
        out = []
        for config in self.configs:
            server = self.servers.get(config.name)
            out.append(
                {
                    "name": config.name,
                    "transport": config.transport,
                    "auth": (config.auth or {}).get("type", "none"),
                    "command": config.url or f"{config.command} {' '.join(config.args)}".strip(),
                    "connected": server is not None,
                    "error": self.errors.get(config.name),
                    "tools": [t.name for t in (server.tools if server else [])],
                }
            )
        return out


def servers_from_config(agents_config: dict) -> list[MCPServerConfig]:
    mcp_config = agents_config.get("mcp") or {}
    if not mcp_config.get("enabled", False):
        return []
    out = []
    for entry in mcp_config.get("servers") or []:
        name = entry.get("name")
        # A url implies http even if transport wasn't spelled out.
        transport = (entry.get("transport") or ("http" if entry.get("url") else "stdio")).lower()

        if not name:
            logger.warning("skipping MCP server entry without a name: %r", entry)
            continue
        if transport == "stdio" and not entry.get("command"):
            logger.warning("skipping stdio MCP server '%s': no command", name)
            continue
        if transport == "http" and not entry.get("url"):
            logger.warning("skipping http MCP server '%s': no url", name)
            continue

        out.append(
            MCPServerConfig(
                name=name,
                transport=transport,
                command=entry.get("command", ""),
                args=list(entry.get("args") or []),
                env={k: str(v) for k, v in (entry.get("env") or {}).items()},
                url=entry.get("url", ""),
                auth=entry.get("auth") or {},
                headers={k: str(v) for k, v in (entry.get("headers") or {}).items()},
                enabled=entry.get("enabled", True),
            )
        )
    return out
