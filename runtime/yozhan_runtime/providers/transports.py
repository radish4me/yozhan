"""Per-provider HTTP transports. Each `*_chat()` function makes one network
call and returns a ChatPayload — (content, tool_calls, usage) — which
ProviderRouter.chat() wraps into a stamped ChatResult. Request/response
conversion is split into pure functions (`*_request_body` / `*_parse_response`)
so the message-format mapping can be unit-tested without any network access.

Token usage is normalized to OpenAI's {prompt_tokens, completion_tokens}
regardless of what the provider calls it, so cost estimation (pricing.py) and
trace logging have one shape to deal with.

- OpenAI, OpenRouter, Grok, and any custom self-hosted endpoint are all
  OpenAI-compatible — one shared function handles all four.
- Anthropic's Messages API and Gemini's generateContent API use different
  request/response shapes (system prompt handling, tool-call representation,
  role names) and get bespoke conversions below.
"""

from __future__ import annotations

import json

import httpx

from yozhan_runtime.providers.errors import ProviderError, ProviderHTTPStatusError

_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 4096

# (content, tool_calls, usage)
ChatPayload = tuple[str | None, list[dict] | None, dict | None]


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.status_code >= 400:
        raise ProviderHTTPStatusError(
            resp.status_code, f"{provider} request failed ({resp.status_code}): {resp.text[:500]}"
        )


# --- OpenAI-compatible (OpenAI, OpenRouter, Grok, custom self-hosted) ------


def openai_compatible_chat(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
) -> ChatPayload:
    headers = {"Authorization": f"Bearer {api_key}"}
    payload: dict = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
    try:
        resp = httpx.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} request failed: {exc}") from exc
    _raise_for_status(resp, provider)
    data = resp.json()
    message = data["choices"][0]["message"]
    usage = data.get("usage")
    normalized = (
        {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        if usage
        else None
    )
    return message.get("content"), message.get("tool_calls"), normalized


# --- Anthropic Messages API -------------------------------------------------


def anthropic_request_body(model: str, messages: list[dict], tools: list[dict] | None) -> dict:
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    body_messages: list[dict] = []

    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        if role == "user":
            body_messages.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            if m.get("tool_calls"):
                content: list[dict] = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for call in m["tool_calls"]:
                    function = call["function"]
                    try:
                        tool_input = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        tool_input = {}
                    content.append(
                        {"type": "tool_use", "id": call["id"], "name": function["name"], "input": tool_input}
                    )
                body_messages.append({"role": "assistant", "content": content})
            else:
                body_messages.append({"role": "assistant", "content": m.get("content") or ""})
        elif role == "tool":
            body_messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                    ],
                }
            )

    body: dict = {"model": model, "max_tokens": _ANTHROPIC_MAX_TOKENS, "messages": body_messages}
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    if tools:
        body["tools"] = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
    return body


def anthropic_parse_response(data: dict) -> ChatPayload:
    blocks = data.get("content", [])
    text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
    tool_calls = [
        {"id": b["id"], "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
        for b in blocks
        if b.get("type") == "tool_use"
    ]
    content = "\n".join(text_parts) if text_parts else None
    raw_usage = data.get("usage") or {}
    usage = (
        {
            "prompt_tokens": raw_usage.get("input_tokens"),
            "completion_tokens": raw_usage.get("output_tokens"),
        }
        if raw_usage
        else None
    )
    return content, (tool_calls or None), usage


def anthropic_chat(
    api_key: str, model: str, messages: list[dict], tools: list[dict] | None, timeout: float
) -> ChatPayload:
    headers = {"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION, "content-type": "application/json"}
    body = anthropic_request_body(model, messages, tools)
    try:
        resp = httpx.post("https://api.anthropic.com/v1/messages", json=body, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ProviderError(f"anthropic request failed: {exc}") from exc
    _raise_for_status(resp, "anthropic")
    return anthropic_parse_response(resp.json())


# --- Google Gemini generateContent API --------------------------------------


def gemini_request_body(messages: list[dict], tools: list[dict] | None) -> tuple[dict, str | None]:
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    contents: list[dict] = []
    tool_call_names: dict[str, str] = {}

    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif role == "assistant":
            if m.get("tool_calls"):
                parts: list[dict] = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for call in m["tool_calls"]:
                    function = call["function"]
                    tool_call_names[call["id"]] = function["name"]
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({"functionCall": {"name": function["name"], "args": args}})
                contents.append({"role": "model", "parts": parts})
            else:
                contents.append({"role": "model", "parts": [{"text": m.get("content") or ""}]})
        elif role == "tool":
            name = tool_call_names.get(m["tool_call_id"], "unknown_function")
            contents.append(
                {
                    "role": "user",
                    "parts": [{"functionResponse": {"name": name, "response": {"result": m["content"]}}}],
                }
            )

    body: dict = {"contents": contents}
    if tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"].get("description", ""),
                        "parameters": t["function"].get("parameters", {"type": "object", "properties": {}}),
                    }
                    for t in tools
                ]
            }
        ]
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return body, system_instruction


def gemini_parse_response(data: dict) -> ChatPayload:
    raw_usage = data.get("usageMetadata") or {}
    usage = (
        {
            "prompt_tokens": raw_usage.get("promptTokenCount"),
            "completion_tokens": raw_usage.get("candidatesTokenCount"),
        }
        if raw_usage
        else None
    )
    candidates = data.get("candidates") or []
    if not candidates:
        return None, None, usage
    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [p["text"] for p in parts if "text" in p]
    tool_calls = [
        {
            "id": f"call_{i}",
            "function": {"name": p["functionCall"]["name"], "arguments": json.dumps(p["functionCall"].get("args", {}))},
        }
        for i, p in enumerate(parts)
        if "functionCall" in p
    ]
    content = "\n".join(text_parts) if text_parts else None
    return content, (tool_calls or None), usage


def gemini_chat(
    api_key: str, model: str, messages: list[dict], tools: list[dict] | None, timeout: float
) -> ChatPayload:
    body, system_instruction = gemini_request_body(messages, tools)
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        resp = httpx.post(url, params={"key": api_key}, json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ProviderError(f"gemini request failed: {exc}") from exc
    _raise_for_status(resp, "gemini")
    return gemini_parse_response(resp.json())
