"""MCP over HTTP with OAuth, tested against a real local HTTP server rather
than mocks — the wire behaviour (SSE framing, 401-then-refresh, session id
echo) is exactly the part most likely to be wrong.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from yozhan_runtime.mcp.client import MCPServer, MCPServerConfig
from yozhan_runtime.mcp.http_transport import (
    HTTPTransport,
    MCPAuthError,
    OAuthClient,
    _parse_sse,
    build_auth,
)

TOOLS = [{"name": "ping", "description": "Ping", "inputSchema": {"type": "object", "properties": {}}}]


class Handler(BaseHTTPRequestHandler):
    """One server standing in for both the MCP endpoint and its token endpoint."""

    issued_tokens: list[str] = []
    accepted_token = "token-1"
    seen_auth: list[str] = []
    use_sse = False
    require_auth = True

    def log_message(self, *args):
        pass  # keep pytest output clean

    def _json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length).decode()

        if self.path == "/token":
            token = f"token-{len(Handler.issued_tokens) + 1}"
            Handler.issued_tokens.append(token)
            Handler.accepted_token = token
            self._json(200, {"access_token": token, "expires_in": 3600})
            return

        auth = self.headers.get("authorization", "")
        Handler.seen_auth.append(auth)
        if Handler.require_auth and auth != f"Bearer {Handler.accepted_token}":
            self._json(401, {"error": "unauthorized"})
            return

        message = json.loads(raw)
        mid, method = message.get("id"), message.get("method")
        if mid is None:
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return

        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {}}
            headers = {"mcp-session-id": "sess-123"}
        elif method == "tools/list":
            result, headers = {"tools": TOOLS}, {}
        elif method == "tools/call":
            result, headers = {"content": [{"type": "text", "text": "pong"}]}, {}
        else:
            self._json(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "nope"}})
            return

        payload = {"jsonrpc": "2.0", "id": mid, "result": result}
        if Handler.use_sse:
            # Lead with a notification, which a client must skip past.
            body = (
                'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}\n\n'
                f"data: {json.dumps(payload)}\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(200, payload, headers)


@pytest.fixture
def server():
    Handler.issued_tokens = []
    Handler.accepted_token = "token-1"
    Handler.seen_auth = []
    Handler.use_sse = False
    Handler.require_auth = True

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


# --- auth configuration -----------------------------------------------------


def test_no_auth_configured():
    assert build_auth(None) is None
    assert build_auth({"type": "none"}) is None


def test_bearer_from_env(monkeypatch):
    monkeypatch.setenv("TEST_MCP_TOKEN", "abc123")
    assert build_auth({"type": "bearer", "token_env": "TEST_MCP_TOKEN"}) == "abc123"


def test_bearer_with_an_empty_env_var_is_an_error(monkeypatch):
    monkeypatch.delenv("TEST_MCP_TOKEN", raising=False)
    with pytest.raises(MCPAuthError, match="empty"):
        build_auth({"type": "bearer", "token_env": "TEST_MCP_TOKEN"})


def test_unknown_auth_type_is_rejected():
    with pytest.raises(MCPAuthError, match="unknown MCP auth type"):
        build_auth({"type": "kerberos"})


def test_oauth_requires_its_three_settings():
    with pytest.raises(MCPAuthError, match="token_url"):
        build_auth({"type": "oauth2", "token_url": "https://x/token"})


# --- OAuth token handling ---------------------------------------------------


def test_token_is_fetched_once_and_cached(server):
    client = OAuthClient(f"{server}/token", "id", "secret")
    assert client.token() == "token-1"
    assert client.token() == "token-1"
    assert len(Handler.issued_tokens) == 1  # cached, not refetched


def test_force_refresh_gets_a_new_token(server):
    client = OAuthClient(f"{server}/token", "id", "secret")
    client.token()
    assert client.token(force_refresh=True) == "token-2"


def test_a_token_endpoint_failure_is_reported_clearly():
    client = OAuthClient("http://127.0.0.1:1/token", "id", "secret")
    with pytest.raises(MCPAuthError, match="could not obtain an OAuth token"):
        client.token()


# --- transport --------------------------------------------------------------


def test_bearer_auth_end_to_end(server):
    transport = HTTPTransport("t", f"{server}/mcp", auth="token-1")
    result = transport.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert result["result"]["tools"][0]["name"] == "ping"
    transport.close()


def test_a_wrong_token_is_reported_as_an_auth_error(server):
    transport = HTTPTransport("t", f"{server}/mcp", auth="wrong")
    with pytest.raises(MCPAuthError, match="rejected our credentials"):
        transport.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    transport.close()


def test_an_expired_oauth_token_is_refreshed_and_the_call_retried(server):
    # The realistic failure for a long-running deployment: the token quietly
    # expires and the server starts answering 401.
    client = OAuthClient(f"{server}/token", "id", "secret")
    transport = HTTPTransport("t", f"{server}/mcp", auth=client)
    transport.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    Handler.accepted_token = "rotated-server-side"
    Handler.seen_auth.clear()

    # The server will 401 the cached token, then accept the freshly issued one.
    result = transport.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    assert result["result"]["tools"][0]["name"] == "ping"
    assert len(Handler.seen_auth) == 2  # one rejected, one retried
    transport.close()


def test_the_session_id_is_captured_and_echoed(server):
    transport = HTTPTransport("t", f"{server}/mcp", auth="token-1")
    transport.request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert transport.session_id == "sess-123"
    transport.close()


def test_sse_responses_are_parsed(server):
    Handler.use_sse = True
    transport = HTTPTransport("t", f"{server}/mcp", auth="token-1")
    result = transport.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert result["result"]["tools"][0]["name"] == "ping"
    transport.close()


def test_sse_parsing_ignores_messages_with_another_id():
    body = (
        'data: {"jsonrpc":"2.0","id":99,"result":{"wrong":true}}\n\n'
        'data: {"jsonrpc":"2.0","id":7,"result":{"right":true}}\n\n'
    )
    assert _parse_sse(body, 7)["result"] == {"right": True}
    assert _parse_sse(body, 1234) is None


# --- full server over HTTP --------------------------------------------------


def test_an_http_mcp_server_handshakes_and_calls_a_tool(server):
    config = MCPServerConfig(
        name="hosted",
        transport="http",
        url=f"{server}/mcp",
        auth={"type": "oauth2", "token_url": f"{server}/token", "client_id": "id", "client_secret": "secret"},
    )
    mcp = MCPServer(config)
    mcp.start()
    try:
        assert [t.qualified_name for t in mcp.tools] == ["mcp__hosted__ping"]
        assert mcp.call("ping", {}) == "pong"
    finally:
        mcp.stop()


def test_an_http_server_without_a_url_is_refused():
    from yozhan_runtime.mcp.client import MCPError

    mcp = MCPServer(MCPServerConfig(name="broken", transport="http"))
    with pytest.raises(MCPError, match="no url"):
        mcp.start()
