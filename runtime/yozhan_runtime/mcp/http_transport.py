"""MCP over Streamable HTTP, with OAuth.

The stdio transport in client.py covers servers you run yourself. This covers
the hosted ones, which are the servers that actually need authentication.

Two auth modes, chosen because they work without a human at a browser:

  bearer  — a static token from an env var or the secret store.
  oauth2  — the client_credentials grant: yozhan exchanges a client id and
            secret for a short-lived access token, caches it, and refreshes it
            when the server answers 401.

The authorization-code grant is deliberately absent. It requires a browser
redirect and a human clicking approve, which a headless VPS process cannot do;
implementing half of it would produce something that appears to support OAuth
and then fails at the moment of use. For servers that only offer auth-code,
issue a long-lived token out of band and use `bearer`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
# Refresh a little early rather than discovering expiry mid-request.
TOKEN_EXPIRY_MARGIN_SECONDS = 30


class MCPAuthError(RuntimeError):
    pass


class OAuthClient:
    """client_credentials token fetch with caching."""

    def __init__(self, token_url: str, client_id: str, client_secret: str, scope: str | None = None):
        if not token_url or not client_id or not client_secret:
            raise MCPAuthError("oauth2 needs token_url, client_id and client_secret")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def token(self, force_refresh: bool = False) -> str:
        with self._lock:
            if not force_refresh and self._token and time.time() < self._expires_at:
                return self._token

            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            if self.scope:
                data["scope"] = self.scope

            try:
                response = httpx.post(self.token_url, data=data, timeout=DEFAULT_TIMEOUT)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MCPAuthError(f"could not obtain an OAuth token from {self.token_url}: {exc}") from exc

            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise MCPAuthError(f"{self.token_url} returned no access_token")

            self._token = token
            self._expires_at = time.time() + max(0, int(payload.get("expires_in", 3600)) - TOKEN_EXPIRY_MARGIN_SECONDS)
            return token


def build_auth(auth_config: dict | None) -> OAuthClient | str | None:
    """Returns an OAuthClient, a static bearer token, or None."""
    auth_config = auth_config or {}
    mode = (auth_config.get("type") or "none").lower()

    if mode in ("none", ""):
        return None

    if mode == "bearer":
        env = auth_config.get("token_env")
        token = os.environ.get(env) if env else auth_config.get("token")
        if not token:
            raise MCPAuthError(f"bearer auth configured but {env or 'token'} is empty")
        return token

    if mode in ("oauth2", "oauth"):
        return OAuthClient(
            token_url=auth_config.get("token_url", ""),
            client_id=os.environ.get(auth_config.get("client_id_env", ""), "") or auth_config.get("client_id", ""),
            client_secret=(
                os.environ.get(auth_config.get("client_secret_env", ""), "") or auth_config.get("client_secret", "")
            ),
            scope=auth_config.get("scope"),
        )

    raise MCPAuthError(f"unknown MCP auth type '{mode}' (expected none, bearer or oauth2)")


class HTTPTransport:
    """Speaks MCP's Streamable HTTP transport.

    Each JSON-RPC request is an HTTP POST. The server may answer with JSON or
    with an SSE stream; both are handled, because which one you get varies by
    server and by whether the response is streamed.
    """

    def __init__(self, name: str, url: str, auth=None, headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.name = name
        self.url = url
        self.auth = auth
        self.extra_headers = headers or {}
        self.timeout = timeout
        self.session_id: str | None = None
        self._client = httpx.Client(timeout=timeout)

    def _headers(self, refresh_token: bool = False) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            # Servers pick their response format from this; accept both.
            "accept": "application/json, text/event-stream",
            **self.extra_headers,
        }
        if isinstance(self.auth, OAuthClient):
            headers["authorization"] = f"Bearer {self.auth.token(force_refresh=refresh_token)}"
        elif isinstance(self.auth, str):
            headers["authorization"] = f"Bearer {self.auth}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    def request(self, payload: dict) -> dict | None:
        response = self._post(payload)

        # An expired OAuth token shows up as a 401; get a fresh one and retry
        # once before giving up, so a long-running deployment doesn't need a
        # restart every hour.
        if response.status_code == 401 and isinstance(self.auth, OAuthClient):
            logger.info("MCP server '%s' returned 401; refreshing the OAuth token", self.name)
            response = self._post(payload, refresh_token=True)

        if response.status_code == 401:
            raise MCPAuthError(f"MCP server '{self.name}' rejected our credentials (401)")
        if response.status_code >= 400:
            raise RuntimeError(f"MCP server '{self.name}' returned {response.status_code}: {response.text[:300]}")

        # The server assigns a session id on initialize; echo it back after.
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id

        if payload.get("id") is None:
            return None  # a notification has no response body worth reading

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/event-stream"):
            return _parse_sse(response.text, payload["id"])
        if not response.text.strip():
            return None
        return response.json()

    def _post(self, payload: dict, refresh_token: bool = False) -> httpx.Response:
        try:
            return self._client.post(self.url, json=payload, headers=self._headers(refresh_token))
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MCP server '{self.name}' unreachable: {exc}") from exc

    def close(self) -> None:
        self._client.close()


def _parse_sse(body: str, request_id) -> dict | None:
    """Pulls the JSON-RPC response with our id out of an SSE stream.

    Servers interleave notifications and progress events in the same stream, so
    taking the first `data:` line would sometimes return someone else's message.
    """
    for block in body.split("\n\n"):
        data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        try:
            message = json.loads("".join(data_lines))
        except json.JSONDecodeError:
            continue
        if message.get("id") == request_id:
            return message
    return None
