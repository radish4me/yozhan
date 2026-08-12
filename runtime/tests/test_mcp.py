"""MCP client. Protocol handling is tested against a real subprocess speaking
JSON-RPC over stdio — a fake server script — rather than against mocks, since
the thing most likely to be wrong is the wire behaviour itself.
"""

import sys
from pathlib import Path

import pytest

from yozhan_runtime.mcp.client import (
    MCPError,
    MCPManager,
    MCPServer,
    MCPServerConfig,
    MCPTool,
    _flatten_content,
    servers_from_config,
)

# A minimal but genuine MCP server: handshake, tools/list, tools/call.
FAKE_SERVER = r'''
import json, sys

TOOLS = [{"name": "echo", "description": "Echo text back",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        continue  # a notification; nothing to answer
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {},
                  "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        args = msg["params"].get("arguments", {})
        if msg["params"]["name"] == "explode":
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "error": {"code": -32000, "message": "tool blew up"}}), flush=True)
            continue
        result = {"content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": mid,
                          "error": {"code": -32601, "message": "no such method"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}), flush=True)
'''

# Emits a log notification before answering, which a client must skip over.
NOISY_SERVER = FAKE_SERVER.replace(
    '    if method == "initialize":',
    '    print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message",\n'
    '                      "params": {"level": "info", "data": "chatter"}}), flush=True)\n'
    '    if method == "initialize":',
)


@pytest.fixture
def server_script(tmp_path):
    path = tmp_path / "fake_mcp.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def config_for(script: Path, name: str = "fake") -> MCPServerConfig:
    return MCPServerConfig(name=name, command=sys.executable, args=[str(script)])


# --- tool naming ------------------------------------------------------------


def test_tools_are_namespaced_by_server():
    tool = MCPTool(server="files", name="read", description="d", input_schema={})
    assert tool.qualified_name == "mcp__files__read"


def test_two_servers_with_the_same_tool_name_do_not_collide():
    a = MCPTool(server="alpha", name="search", description="", input_schema={})
    b = MCPTool(server="beta", name="search", description="", input_schema={})
    assert a.qualified_name != b.qualified_name


def test_openai_tool_shape_carries_the_schema():
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tool = MCPTool(server="s", name="find", description="Find things", input_schema=schema).as_openai_tool()
    assert tool["function"]["name"] == "mcp__s__find"
    assert tool["function"]["parameters"] == schema
    assert "[s]" in tool["function"]["description"]


def test_a_tool_without_a_schema_still_produces_valid_parameters():
    tool = MCPTool(server="s", name="ping", description="", input_schema={}).as_openai_tool()
    assert tool["function"]["parameters"] == {"type": "object", "properties": {}}


# --- content flattening -----------------------------------------------------


def test_text_blocks_are_joined():
    assert _flatten_content({"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}) == "a\nb"


def test_error_results_are_marked():
    out = _flatten_content({"content": [{"type": "text", "text": "nope"}], "isError": True})
    assert out.startswith("error:")


def test_resources_and_unknown_blocks_degrade_readably():
    assert "hello" in _flatten_content({"content": [{"type": "resource", "resource": {"text": "hello"}}]})
    assert "image" in _flatten_content({"content": [{"type": "image", "data": "..."}]})


def test_empty_content_says_so():
    assert _flatten_content({"content": []}) == "(no output)"


# --- live subprocess --------------------------------------------------------


def test_handshake_and_tool_discovery(server_script):
    server = MCPServer(config_for(server_script))
    server.start()
    try:
        assert [t.name for t in server.tools] == ["echo"]
        assert server.tools[0].qualified_name == "mcp__fake__echo"
    finally:
        server.stop()


def test_calling_a_tool_returns_its_text(server_script):
    server = MCPServer(config_for(server_script))
    server.start()
    try:
        assert server.call("echo", {"text": "hi"}) == "echo: hi"
    finally:
        server.stop()


def test_a_server_error_is_raised_as_mcp_error(server_script):
    server = MCPServer(config_for(server_script))
    server.start()
    try:
        with pytest.raises(MCPError, match="tool blew up"):
            server.call("explode", {})
    finally:
        server.stop()


def test_notifications_are_skipped_while_waiting_for_a_response(tmp_path):
    # Servers legitimately emit log/progress notifications mid-request; a
    # client that treats the first line as its answer breaks on real servers.
    script = tmp_path / "noisy.py"
    script.write_text(NOISY_SERVER, encoding="utf-8")
    server = MCPServer(config_for(script, "noisy"))
    server.start()
    try:
        assert server.call("echo", {"text": "still works"}) == "echo: still works"
    finally:
        server.stop()


def test_a_missing_command_raises_a_clear_error():
    server = MCPServer(MCPServerConfig(name="ghost", command="definitely-not-a-real-binary"))
    with pytest.raises(MCPError, match="not found"):
        server.start()


# --- manager ----------------------------------------------------------------


def test_manager_exposes_tools_and_routes_calls(server_script):
    manager = MCPManager([config_for(server_script)])
    manager.start()
    try:
        assert manager.handles("mcp__fake__echo")
        assert not manager.handles("read_file")
        assert manager.call("mcp__fake__echo", {"text": "routed"}) == "echo: routed"
    finally:
        manager.stop()


def test_one_broken_server_does_not_stop_the_others(server_script):
    # A misconfigured MCP server must not prevent yozhan from starting.
    manager = MCPManager(
        [config_for(server_script), MCPServerConfig(name="broken", command="definitely-not-a-real-binary")]
    )
    manager.start()
    try:
        assert [t.qualified_name for t in manager.tools()] == ["mcp__fake__echo"]
        described = {d["name"]: d for d in manager.describe()}
        assert described["fake"]["connected"] is True
        assert described["broken"]["connected"] is False
        assert "not found" in described["broken"]["error"]
    finally:
        manager.stop()


def test_calling_an_unknown_tool_returns_an_error_string(server_script):
    manager = MCPManager([config_for(server_script)])
    manager.start()
    try:
        assert manager.call("mcp__fake__nope", {}).startswith("error:")
    finally:
        manager.stop()


# --- config -----------------------------------------------------------------


def test_disabled_config_yields_no_servers():
    assert servers_from_config({"mcp": {"enabled": False, "servers": [{"name": "x", "command": "y"}]}}) == []
    assert servers_from_config({}) == []


def test_config_parses_servers():
    servers = servers_from_config(
        {
            "mcp": {
                "enabled": True,
                "servers": [
                    {"name": "files", "command": "npx", "args": ["-y", "pkg"], "env": {"TOKEN": "abc"}},
                    {"name": "off", "command": "x", "enabled": False},
                ],
            }
        }
    )
    assert [s.name for s in servers] == ["files", "off"]
    assert servers[0].args == ["-y", "pkg"]
    assert servers[0].env == {"TOKEN": "abc"}
    # servers_from_config parses; MCPManager is what drops disabled entries.
    assert [c.name for c in MCPManager(servers).configs] == ["files"]


def test_incomplete_entries_are_skipped_not_fatal():
    servers = servers_from_config(
        {"mcp": {"enabled": True, "servers": [{"name": "no-command"}, {"command": "no-name"}]}}
    )
    assert servers == []
