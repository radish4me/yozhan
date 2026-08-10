from pathlib import Path

from yozhan_runtime.agents.orchestrator import Orchestrator
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ChatResult, ProviderError
from yozhan_runtime.skills.manager import SkillManager

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

AGENTS_CONFIG = {
    "defaults": {"fallback_chain": "default"},
    "agents": {
        "researcher": {"fallback_chain": "local_first", "mode": "on-demand"},
        "coder": {"provider": "anthropic", "model": "claude-sonnet-5", "mode": "on-demand"},
    },
}

PROVIDERS_CONFIG = {
    "fallback_chains": {
        "default": [{"provider": "local", "model": "qwen3.5-0.8b"}],
        "local_first": [{"provider": "local", "model": "qwen3.5-0.8b"}],
    }
}


class FakeRouter:
    """Only 'local' has transport — mirrors the real ProviderRouter's Phase 3 boundary."""

    def __init__(self, local_reply: str = "ok"):
        self.local_reply = local_reply
        self.calls: list[tuple[str, str | None]] = []

    def chat(self, provider, model, messages, tools=None, timeout=120.0):
        self.calls.append((provider, model))
        if provider == "local":
            return ChatResult(provider="local", model=model, content=self.local_reply)
        raise ProviderError(f"provider '{provider}' has no transport implemented yet")


def make_orchestrator(tmp_path, router):
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    memory = SessionStore(user_id="test", db_dir=tmp_path)
    return Orchestrator(
        router=router,
        skills=manager,
        memory=memory,
        agents_config=AGENTS_CONFIG,
        providers_config=PROVIDERS_CONFIG,
    )


def test_dispatch_resolves_each_agent_independently(tmp_path):
    router = FakeRouter()
    orchestrator = make_orchestrator(tmp_path, router)

    results = {r.agent: r for r in orchestrator.dispatch_many([("researcher", "look up X"), ("coder", "write Y")])}

    assert results["researcher"].provider == "local"
    assert results["researcher"].error is None
    assert results["researcher"].result.output == "ok"

    assert results["coder"].provider == "anthropic"
    assert results["coder"].model == "claude-sonnet-5"
    assert results["coder"].error is not None
    assert "no transport implemented" in results["coder"].error
    assert results["coder"].result is None


def test_one_agent_failure_does_not_block_others(tmp_path):
    router = FakeRouter()
    orchestrator = make_orchestrator(tmp_path, router)

    results = orchestrator.dispatch_many([("coder", "fails"), ("researcher", "succeeds")])

    assert len(results) == 2
    assert results[0].error is not None
    assert results[1].error is None
    assert results[1].result.output == "ok"


def test_each_agent_gets_its_own_session(tmp_path):
    router = FakeRouter()
    orchestrator = make_orchestrator(tmp_path, router)

    orchestrator.dispatch("researcher", "task one")
    orchestrator.dispatch("researcher", "task two")

    history = orchestrator.memory.get_history("researcher")
    assert [m["content"] for m in history if m["role"] == "user"] == ["task one", "task two"]
