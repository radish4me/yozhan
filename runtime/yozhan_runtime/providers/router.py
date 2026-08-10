"""Resolves a provider/model reference (or a fallback chain) to an actual
OpenAI-compatible chat completion call. Phase 1 scope: local llama.cpp only,
sequential fallback. Multi-key rotation and parallel fan-out land in Phase 4
per ROADMAP.md.
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
    content: str


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

    def chat_local(self, messages: list[dict], model: str | None = None, timeout: float = 120.0) -> ChatResult:
        """Calls llama-server's OpenAI-compatible /v1/chat/completions endpoint."""
        base_url = self._local_base_url().rstrip("/")
        model = model or self.default_local_model()
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages},
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"local provider request failed: {exc}") from exc

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResult(provider="local", model=model, content=content)
