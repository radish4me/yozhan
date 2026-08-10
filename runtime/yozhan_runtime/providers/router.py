"""Resolves a provider/model reference — a direct pin, a sequential fallback
chain, or a parallel fan-out — to actual chat completion calls.

`chat()` is the single-call dispatch seam: 'local' talks to llama.cpp
directly; every other configured provider goes through its transport in
transports.py with per-provider API key rotation (keyring.py) on
rate-limit/auth failures. `chat_with_fallback()` walks a sequential chain,
falling through to the next entry on any ProviderError. `chat_parallel()`
fans a `mode: parallel` chain's members out concurrently and returns every
outcome (success or error) rather than raising on a partial failure.
See ARCHITECTURE.md section 4.1 and ROADMAP.md Phase 4.
"""

from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass
from typing import Callable

import httpx

from yozhan_runtime.config import load_providers
from yozhan_runtime.providers import transports
from yozhan_runtime.providers.errors import ProviderError, ProviderHTTPStatusError
from yozhan_runtime.providers.keyring import ROTATE_ON_STATUS, KeyRing

__all__ = ["ProviderError", "ProviderHTTPStatusError", "ChatResult", "ProviderRouter"]

_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "grok": "https://api.x.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
_OPENAI_COMPATIBLE_TYPES = {"openai", "grok", "openrouter", "openai_compatible"}


@dataclass
class ChatResult:
    provider: str
    model: str
    content: str | None
    tool_calls: list[dict] | None = None


class ProviderRouter:
    def __init__(self, config: dict | None = None):
        self.config = config or load_providers()
        self._keyrings: dict[str, KeyRing] = {}

    def _local_base_url(self) -> str:
        override = os.environ.get("LLAMA_SERVER_URL")
        if override:
            return override
        return self.config["providers"]["local"]["base_url"]

    def default_local_model(self) -> str:
        return self.config["providers"]["local"]["default_model"]

    def _keyring(self, provider: str) -> KeyRing:
        if provider not in self._keyrings:
            provider_cfg = self.config["providers"].get(provider, {})
            self._keyrings[provider] = KeyRing(provider, provider_cfg.get("api_keys", []))
        return self._keyrings[provider]

    def chat(
        self,
        provider: str,
        model: str | None,
        messages: list[dict],
        tools: list[dict] | None = None,
        timeout: float = 120.0,
    ) -> ChatResult:
        if provider == "local":
            return self.chat_local(messages, model=model, tools=tools, timeout=timeout)

        provider_cfg = self.config["providers"].get(provider)
        if provider_cfg is None:
            raise ProviderError(f"unknown provider '{provider}' (not in config/providers.yaml)")
        provider_type = provider_cfg.get("type", provider)
        keyring = self._keyring(provider)
        if not keyring:
            raise ProviderError(
                f"no API key configured for provider '{provider}' (set one of its api_keys env vars)"
            )

        call = self._build_call(provider, provider_type, provider_cfg, model, messages, tools, timeout)
        content, tool_calls = self._call_with_key_rotation(provider, keyring, call)
        return ChatResult(provider=provider, model=model, content=content, tool_calls=tool_calls)

    def _build_call(
        self, provider: str, provider_type: str, provider_cfg: dict, model, messages, tools, timeout
    ) -> Callable[[str], tuple[str | None, list[dict] | None]]:
        if provider_type == "anthropic":
            return lambda key: transports.anthropic_chat(key, model, messages, tools, timeout)
        if provider_type == "gemini":
            return lambda key: transports.gemini_chat(key, model, messages, tools, timeout)
        if provider_type in _OPENAI_COMPATIBLE_TYPES:
            base_url = provider_cfg.get("base_url") or _DEFAULT_BASE_URLS.get(provider_type)
            if not base_url:
                raise ProviderError(f"provider '{provider}' (type '{provider_type}') has no base_url configured")
            return lambda key: transports.openai_compatible_chat(
                provider, base_url, key, model, messages, tools, timeout
            )
        raise ProviderError(f"provider type '{provider_type}' has no transport implemented")

    @staticmethod
    def _call_with_key_rotation(
        provider: str, keyring: KeyRing, call: Callable[[str], tuple[str | None, list[dict] | None]]
    ) -> tuple[str | None, list[dict] | None]:
        last_error: Exception | None = None
        for _ in range(len(keyring)):
            key = keyring.current()
            try:
                return call(key)
            except ProviderHTTPStatusError as exc:
                last_error = exc
                if exc.status_code in ROTATE_ON_STATUS and len(keyring) > 1:
                    keyring.rotate()
                    continue
                raise
        raise ProviderError(f"all configured keys for provider '{provider}' failed: {last_error}")

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

    def chat_with_fallback(
        self,
        chain: list[dict],
        messages: list[dict],
        tools: list[dict] | None = None,
        timeout: float = 120.0,
    ) -> ChatResult:
        """Tries each {provider, model} entry in order, falling through to the
        next on any ProviderError (timeout, rate limit, exhausted keys, ...)."""
        errors = []
        for entry in chain:
            try:
                return self.chat(entry["provider"], entry.get("model"), messages, tools=tools, timeout=timeout)
            except ProviderError as exc:
                errors.append(f"{entry['provider']}/{entry.get('model')}: {exc}")
        raise ProviderError("every provider in the fallback chain failed: " + " | ".join(errors))

    def chat_parallel(
        self,
        members: list[dict],
        messages: list[dict],
        tools: list[dict] | None = None,
        timeout: float = 120.0,
    ) -> list[dict]:
        """Dispatches every member concurrently. Returns one entry per member:
        {"provider", "model", "result": ChatResult | None, "error": str | None} —
        never raises on a partial failure, unlike chat_with_fallback()."""
        if not members:
            return []

        def run_one(entry: dict) -> dict:
            try:
                result = self.chat(entry["provider"], entry.get("model"), messages, tools=tools, timeout=timeout)
                return {"provider": entry["provider"], "model": entry.get("model"), "result": result, "error": None}
            except ProviderError as exc:
                return {
                    "provider": entry["provider"],
                    "model": entry.get("model"),
                    "result": None,
                    "error": str(exc),
                }

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(members)) as pool:
            return list(pool.map(run_one, members))
