"""Resolves a provider/model reference (or a fallback chain) to an actual
OpenAI-compatible chat completion call. `chat()` is the dispatch seam every
agent goes through: today only the `local` provider (llama.cpp) has real
transport wired up. Any other provider name resolves correctly (Phase 3's
per-agent model assignment) but raises ProviderError until Phase 4 wires
its HTTP client, key rotation, and fallback-chain walking per ROADMAP.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from yozhan_runtime.config import load_providers


class ProviderError(RuntimeError):
    pass


@dataclass
class ChatResult:
    provider: str
    model: str
    content: str | None
    tool_calls: list[dict] | None = None


class ProviderRouter:
    def __init__(self, config: dict | None = None):
        self.config = config or load_providers()

    def _local_base_url(self) -> str:
        override = os.environ.get("LLAMA_SERVER_URL")
        if override:
            return override
        return self.config["providers"]["local"]["base_url"]

    def default_local_model(self) -> str:
        return self.config["providers"]["local"]["default_model"]

    def chat(
        self,
        provider: str,
        model: str | None,
        messages: list[dict],
        tools: list[dict] | None = None,
        timeout: float = 120.0,
    ) -> ChatResult:
        """Dispatches to the transport for `provider`. See module docstring."""
        if provider == "local":
            return self.chat_local(messages, model=model, tools=tools, timeout=timeout)
        raise ProviderError(
            f"provider '{provider}' has no transport implemented yet — "
            "multi-provider dispatch (keys, fallback walking, parallel fan-out) "
            "lands in Phase 4 (see ROADMAP.md)"
        )

    def chat_local(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        timeout: float = 120.0,
    ) -> ChatResult:
        """Calls llama-server's OpenAI-compatible /v1/chat/completions endpoint."""
        base_url = self._local_base_url().rstrip("/")
        model = model or self.default_local_model()
        payload: dict = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
        try:
            resp = httpx.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"local provider request failed: {exc}") from exc

        message = resp.json()["choices"][0]["message"]
        return ChatResult(
            provider="local",
            model=model,
            content=message.get("content"),
            tool_calls=message.get("tool_calls"),
        )
