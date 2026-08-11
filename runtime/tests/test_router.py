"""Tests ProviderRouter's dispatch/rotation/fallback/parallel logic. All
transport functions are monkeypatched — no real network calls.
"""

import pytest

from yozhan_runtime.providers.errors import ProviderError, ProviderHTTPStatusError
from yozhan_runtime.providers.router import ChatResult, ProviderRouter

CONFIG = {
    "providers": {
        "local": {"base_url": "http://local:8080/v1", "default_model": "qwen3.5-0.8b"},
        "anthropic": {"type": "anthropic", "api_keys": [{"env": "TEST_ANTHROPIC_KEY"}]},
        "gemini": {"type": "gemini", "api_keys": [{"env": "TEST_GEMINI_KEY_1"}, {"env": "TEST_GEMINI_KEY_2"}]},
        "openrouter": {"type": "openrouter", "api_keys": [{"env": "TEST_OPENROUTER_KEY"}]},
    }
}


def make_router(monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-key")
    monkeypatch.setenv("TEST_GEMINI_KEY_1", "gem-key-1")
    monkeypatch.setenv("TEST_GEMINI_KEY_2", "gem-key-2")
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "or-key")
    return ProviderRouter(config=CONFIG)


def test_local_dispatch_uses_no_keyring(monkeypatch):
    router = ProviderRouter(config=CONFIG)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "hi", "tool_calls": None}}]}

    monkeypatch.setattr("httpx.post", lambda *a, **k: FakeResponse())
    result = router.chat("local", None, [{"role": "user", "content": "hi"}])
    assert result.content == "hi"


def test_unconfigured_key_raises_clear_error(monkeypatch):
    router = ProviderRouter(config=CONFIG)
    with pytest.raises(ProviderError, match="no API key configured"):
        router.chat("anthropic", "claude-sonnet-5", [{"role": "user", "content": "hi"}])


def test_unknown_provider_raises():
    router = ProviderRouter(config=CONFIG)
    with pytest.raises(ProviderError, match="unknown provider"):
        router.chat("does-not-exist", "some-model", [{"role": "user", "content": "hi"}])


def test_key_rotates_on_429_then_succeeds(monkeypatch):
    router = make_router(monkeypatch)
    calls = []

    def fake_gemini_chat(api_key, model, messages, tools, timeout):
        calls.append(api_key)
        if api_key == "gem-key-1":
            raise ProviderHTTPStatusError(429, "rate limited")
        return "ok", None, None

    monkeypatch.setattr("yozhan_runtime.providers.transports.gemini_chat", fake_gemini_chat)
    result = router.chat("gemini", "gemini-2.5-flash", [{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert calls == ["gem-key-1", "gem-key-2"]


def test_non_rotate_status_raises_immediately_without_trying_other_keys(monkeypatch):
    router = make_router(monkeypatch)
    calls = []

    def fake_gemini_chat(api_key, model, messages, tools, timeout):
        calls.append(api_key)
        raise ProviderHTTPStatusError(500, "server error")

    monkeypatch.setattr("yozhan_runtime.providers.transports.gemini_chat", fake_gemini_chat)
    with pytest.raises(ProviderError):
        router.chat("gemini", "gemini-2.5-flash", [{"role": "user", "content": "hi"}])

    assert calls == ["gem-key-1"]


def test_all_keys_exhausted_raises_clear_error(monkeypatch):
    router = make_router(monkeypatch)

    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.gemini_chat",
        lambda *a, **k: (_ for _ in ()).throw(ProviderHTTPStatusError(429, "rate limited")),
    )
    with pytest.raises(ProviderError, match="all configured keys"):
        router.chat("gemini", "gemini-2.5-flash", [{"role": "user", "content": "hi"}])


def test_fallback_chain_walks_to_next_provider_on_failure(monkeypatch):
    router = make_router(monkeypatch)

    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.anthropic_chat",
        lambda *a, **k: (_ for _ in ()).throw(ProviderHTTPStatusError(500, "boom")),
    )
    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.gemini_chat", lambda *a, **k: ("gemini saved the day", None, None)
    )

    chain = [{"provider": "anthropic", "model": "claude-sonnet-5"}, {"provider": "gemini", "model": "gemini-2.5-flash"}]
    result = router.chat_with_fallback(chain, [{"role": "user", "content": "hi"}])

    assert result.provider == "gemini"
    assert result.content == "gemini saved the day"


def test_fallback_chain_raises_when_every_entry_fails(monkeypatch):
    router = make_router(monkeypatch)
    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.anthropic_chat",
        lambda *a, **k: (_ for _ in ()).throw(ProviderHTTPStatusError(500, "boom")),
    )
    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.gemini_chat",
        lambda *a, **k: (_ for _ in ()).throw(ProviderHTTPStatusError(500, "boom")),
    )

    chain = [{"provider": "anthropic", "model": "x"}, {"provider": "gemini", "model": "y"}]
    with pytest.raises(ProviderError, match="every provider in the fallback chain failed"):
        router.chat_with_fallback(chain, [{"role": "user", "content": "hi"}])


def test_chat_parallel_dispatches_all_members_concurrently(monkeypatch):
    router = make_router(monkeypatch)

    monkeypatch.setattr("yozhan_runtime.providers.transports.gemini_chat", lambda *a, **k: ("gemini result", None, None))
    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.openai_compatible_chat", lambda *a, **k: ("openrouter result", None, None)
    )
    monkeypatch.setattr(
        router, "chat_local", lambda messages, model=None, tools=None, timeout=120.0: ChatResult(
            provider="local", model=model or "qwen3.5-0.8b", content="local result"
        )
    )

    members = [
        {"provider": "openrouter", "model": "qwen/qwen-2.5-coder"},
        {"provider": "gemini", "model": "gemini-2.5-flash"},
        {"provider": "local", "model": "qwen3.5-0.8b"},
    ]
    outcomes = router.chat_parallel(members, [{"role": "user", "content": "hi"}])

    assert len(outcomes) == 3
    assert {o["provider"] for o in outcomes} == {"openrouter", "gemini", "local"}
    assert all(o["error"] is None for o in outcomes)


def test_chat_parallel_partial_failure_does_not_raise(monkeypatch):
    router = make_router(monkeypatch)

    monkeypatch.setattr("yozhan_runtime.providers.transports.gemini_chat", lambda *a, **k: ("ok", None, None))
    monkeypatch.setattr(
        "yozhan_runtime.providers.transports.openai_compatible_chat",
        lambda *a, **k: (_ for _ in ()).throw(ProviderHTTPStatusError(500, "boom")),
    )

    members = [{"provider": "openrouter", "model": "x"}, {"provider": "gemini", "model": "y"}]
    outcomes = router.chat_parallel(members, [{"role": "user", "content": "hi"}])

    by_provider = {o["provider"]: o for o in outcomes}
    assert by_provider["gemini"]["error"] is None
    assert by_provider["openrouter"]["error"] is not None
