"""Tests the pure request/response conversion functions in transports.py —
no network access, just verifying the Anthropic/Gemini <-> OpenAI-style
message and tool-call format mapping is structurally correct.
"""

import json

from yozhan_runtime.providers.transports import (
    anthropic_parse_response,
    anthropic_request_body,
    gemini_parse_response,
    gemini_request_body,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "search the web",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def test_anthropic_request_body_extracts_system_and_converts_tools():
    messages = [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
    body = anthropic_request_body("claude-sonnet-5", messages, TOOLS)

    assert body["system"] == "be helpful"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["tools"][0]["name"] == "web_search"
    assert body["tools"][0]["input_schema"]["required"] == ["query"]


def test_anthropic_request_body_round_trips_tool_call():
    messages = [
        {"role": "user", "content": "search for X"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {"name": "web_search", "arguments": '{"query": "X"}'}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "no results"},
    ]
    body = anthropic_request_body("claude-sonnet-5", messages, None)

    assistant_msg = body["messages"][1]
    assert assistant_msg["content"][0]["type"] == "tool_use"
    assert assistant_msg["content"][0]["input"] == {"query": "X"}

    tool_result_msg = body["messages"][2]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"
    assert tool_result_msg["content"][0]["tool_use_id"] == "call_1"


def test_anthropic_parse_response_extracts_text_and_tool_use():
    data = {
        "content": [
            {"type": "text", "text": "let me check"},
            {"type": "tool_use", "id": "call_9", "name": "web_search", "input": {"query": "X"}},
        ]
    }
    content, tool_calls, _usage = anthropic_parse_response(data)

    assert content == "let me check"
    assert tool_calls[0]["id"] == "call_9"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"query": "X"}


def test_gemini_request_body_maps_roles_and_tools():
    messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    body, system_instruction = gemini_request_body(messages, TOOLS)

    assert system_instruction == "be helpful"
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
    ]
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "web_search"


def test_gemini_request_body_round_trips_tool_call_with_name_lookup():
    messages = [
        {"role": "user", "content": "search for X"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {"name": "web_search", "arguments": '{"query": "X"}'}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "no results"},
    ]
    body, _ = gemini_request_body(messages, None)

    assistant_content = body["contents"][1]
    assert assistant_content["role"] == "model"
    assert assistant_content["parts"][0]["functionCall"]["name"] == "web_search"

    tool_response_content = body["contents"][2]
    assert tool_response_content["parts"][0]["functionResponse"]["name"] == "web_search"
    assert tool_response_content["parts"][0]["functionResponse"]["response"]["result"] == "no results"


def test_gemini_parse_response_extracts_text_and_function_call():
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "checking"},
                        {"functionCall": {"name": "web_search", "args": {"query": "X"}}},
                    ]
                }
            }
        ]
    }
    content, tool_calls, _usage = gemini_parse_response(data)

    assert content == "checking"
    assert tool_calls[0]["function"]["name"] == "web_search"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"query": "X"}


def test_gemini_parse_response_handles_no_candidates():
    content, tool_calls, _usage = gemini_parse_response({"candidates": []})
    assert content is None
    assert tool_calls is None
