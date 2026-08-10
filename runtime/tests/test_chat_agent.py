from pathlib import Path

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ChatResult
from yozhan_runtime.skills.manager import SkillManager

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


class FakeRouter:
    """Stands in for ProviderRouter so tests don't need a live llama-server."""

    def __init__(self, responses: list[ChatResult]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, provider, model, messages, tools=None, timeout=120.0):
        self.calls.append(messages)
        return self._responses.pop(0)


class ChainFakeRouter:
    """Only implements chat_with_fallback — used to verify ChatAgent routes
    through it (instead of plain .chat()) whenever a `chain` is configured."""

    def __init__(self, response: ChatResult):
        self.response = response
        self.chains_seen: list[list[dict]] = []

    def chat_with_fallback(self, chain, messages, tools=None, timeout=120.0):
        self.chains_seen.append(chain)
        return self.response


def make_skills():
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    return manager


def test_plain_reply_persists_history(tmp_path):
    router = FakeRouter([ChatResult(provider="local", model="qwen3.5-0.8b", content="hello there")])
    memory = SessionStore(user_id="test", db_dir=tmp_path)
    agent = ChatAgent(router=router, skills=make_skills(), memory=memory, session_id="s1")

    result = agent.run("hi")

    assert result.output == "hello there"
    assert memory.get_history("s1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]


def test_tool_call_round_trip_is_executed_and_final_answer_persisted(tmp_path):
    tool_call = {
        "id": "call_1",
        "function": {"name": "web_search", "arguments": '{"query": "yozhan"}'},
    }
    router = FakeRouter(
        [
            ChatResult(provider="local", model="qwen3.5-0.8b", content=None, tool_calls=[tool_call]),
            ChatResult(provider="local", model="qwen3.5-0.8b", content="here's what I found"),
        ]
    )
    memory = SessionStore(user_id="test", db_dir=tmp_path)
    agent = ChatAgent(router=router, skills=make_skills(), memory=memory, session_id="s1")

    result = agent.run("search for yozhan")

    assert result.output == "here's what I found"
    # second router call should include the tool result as a "tool" message
    second_call_messages = router.calls[1]
    tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "not configured" in tool_messages[0]["content"]
    # persisted history only has the user turn and the final assistant answer,
    # not the intermediate tool exchange
    assert memory.get_history("s1") == [
        {"role": "user", "content": "search for yozhan"},
        {"role": "assistant", "content": "here's what I found"},
    ]


def test_exceeding_tool_iteration_limit_returns_fallback(tmp_path):
    tool_call = {"id": "call_1", "function": {"name": "web_search", "arguments": "{}"}}
    responses = [
        ChatResult(provider="local", model="m", content=None, tool_calls=[tool_call]) for _ in range(3)
    ]
    router = FakeRouter(responses)
    memory = SessionStore(user_id="test", db_dir=tmp_path)
    agent = ChatAgent(
        router=router, skills=make_skills(), memory=memory, session_id="s1", max_tool_iterations=3
    )

    result = agent.run("loop forever")

    assert "tool-call limit" in result.output
    assert result.metadata.get("truncated") is True


def test_chain_configured_agent_dispatches_via_fallback_walking(tmp_path):
    router = ChainFakeRouter(ChatResult(provider="gemini", model="gemini-2.5-flash", content="via fallback chain"))
    memory = SessionStore(user_id="test", db_dir=tmp_path)
    chain = [{"provider": "anthropic", "model": "claude-sonnet-5"}, {"provider": "gemini", "model": "gemini-2.5-flash"}]
    agent = ChatAgent(router=router, skills=make_skills(), memory=memory, session_id="s1", chain=chain)

    result = agent.run("hi")

    assert result.output == "via fallback chain"
    assert router.chains_seen == [chain]
