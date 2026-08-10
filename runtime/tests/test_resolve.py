import pytest

from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent

AGENTS_CONFIG = {
    "defaults": {"fallback_chain": "default", "sandbox": "non-privileged-only"},
    "agents": {
        "orchestrator": {"fallback_chain": "default", "mode": "on-demand"},
        "researcher": {"subagent_of": "orchestrator", "fallback_chain": "local_first", "mode": "on-demand"},
        "coder": {
            "subagent_of": "orchestrator",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "mode": "on-demand",
        },
        "reviewer": {"subagent_of": "orchestrator", "fallback_chain": "cheap_parallel_fanout", "mode": "on-demand"},
    },
}

PROVIDERS_CONFIG = {
    "fallback_chains": {
        "default": [
            {"provider": "gemini", "model": "gemini-2.5-flash"},
            {"provider": "local", "model": "qwen3.5-0.8b"},
        ],
        "local_first": [
            {"provider": "local", "model": "qwen3.5-0.8b"},
            {"provider": "openrouter", "model": "google/gemini-flash-1.5"},
        ],
        "cheap_parallel_fanout": {
            "mode": "parallel",
            "members": [
                {"provider": "openrouter", "model": "qwen/qwen-2.5-coder"},
                {"provider": "local", "model": "qwen3.5-0.8b"},
            ],
        },
    }
}


def test_direct_pin_wins_over_fallback_chain():
    resolved = resolve_agent("coder", AGENTS_CONFIG, PROVIDERS_CONFIG)
    assert resolved.provider == "anthropic"
    assert resolved.model == "claude-sonnet-5"
    assert resolved.subagent_of == "orchestrator"


def test_named_fallback_chain_resolves_to_first_entry():
    resolved = resolve_agent("researcher", AGENTS_CONFIG, PROVIDERS_CONFIG)
    assert resolved.provider == "local"
    assert resolved.model == "qwen3.5-0.8b"


def test_parallel_chain_resolves_to_first_member():
    resolved = resolve_agent("reviewer", AGENTS_CONFIG, PROVIDERS_CONFIG)
    assert resolved.provider == "openrouter"
    assert resolved.model == "qwen/qwen-2.5-coder"


def test_subagents_resolve_independently_of_parent():
    parent = resolve_agent("orchestrator", AGENTS_CONFIG, PROVIDERS_CONFIG)
    child = resolve_agent("coder", AGENTS_CONFIG, PROVIDERS_CONFIG)
    assert (parent.provider, parent.model) != (child.provider, child.model)


def test_sandbox_falls_back_to_defaults():
    resolved = resolve_agent("researcher", AGENTS_CONFIG, PROVIDERS_CONFIG)
    assert resolved.sandbox == "non-privileged-only"


def test_unknown_agent_raises():
    with pytest.raises(AgentConfigError):
        resolve_agent("nonexistent", AGENTS_CONFIG, PROVIDERS_CONFIG)


def test_missing_fallback_chain_reference_raises():
    bad_agents = {"defaults": {}, "agents": {"x": {"fallback_chain": "does_not_exist"}}}
    with pytest.raises(AgentConfigError):
        resolve_agent("x", bad_agents, PROVIDERS_CONFIG)


def test_no_pin_and_no_resolvable_chain_raises():
    bad_agents = {"defaults": {}, "agents": {"x": {}}}
    with pytest.raises(AgentConfigError):
        resolve_agent("x", bad_agents, PROVIDERS_CONFIG)


def test_real_repo_agents_yaml_resolves():
    """Sanity check against the actual shipped config/agents.yaml + providers.yaml."""
    resolved = resolve_agent("researcher")
    assert resolved.provider == "local"
