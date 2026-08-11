"""Trace logging: what ChatAgent records while running, and the aggregation
the Phase 7 cost report reads back out."""

from pathlib import Path

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.memory.curated import CuratedMemory
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ChatResult
from yozhan_runtime.skills.manager import SkillManager

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


class FakeRouter:
    def __init__(self, responses):
        self._responses = list(responses)
        self.seen_messages = []

    def chat(self, provider, model, messages, tools=None, timeout=120.0):
        self.seen_messages.append(messages)
        return self._responses.pop(0)


def make_skills():
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    return manager


def test_model_call_is_traced_with_tokens_and_cost(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    router = FakeRouter(
        [
            ChatResult(
                provider="anthropic",
                model="claude-sonnet-5",
                content="done",
                usage={"prompt_tokens": 100, "completion_tokens": 50},
                cost_usd=0.00105,
            )
        ]
    )
    agent = ChatAgent(router=router, skills=make_skills(), memory=store, session_id="s1")

    result = agent.run("hi")

    task_traces = store.get_task_traces(result.metadata["task_id"])
    assert len(task_traces) == 1
    trace = task_traces[0]
    assert trace["kind"] == "model_call"
    assert trace["provider"] == "anthropic"
    assert trace["prompt_tokens"] == 100
    assert trace["cost_usd"] == 0.00105
    assert trace["ok"] == 1
    assert trace["latency_ms"] >= 0


def test_tool_calls_are_traced_separately(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    tool_call = {"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "x"}'}}
    router = FakeRouter(
        [
            ChatResult(provider="local", model="m", content=None, tool_calls=[tool_call]),
            ChatResult(provider="local", model="m", content="final"),
        ]
    )
    agent = ChatAgent(router=router, skills=make_skills(), memory=store, session_id="s1")

    result = agent.run("search")

    kinds = [t["kind"] for t in store.get_task_traces(result.metadata["task_id"])]
    assert kinds == ["model_call", "tool_call", "model_call"]


def test_failing_tool_is_traced_as_a_failure(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    tool_call = {"id": "c1", "function": {"name": "does_not_exist", "arguments": "{}"}}
    router = FakeRouter(
        [
            ChatResult(provider="local", model="m", content=None, tool_calls=[tool_call]),
            ChatResult(provider="local", model="m", content="recovered"),
        ]
    )
    agent = ChatAgent(router=router, skills=make_skills(), memory=store, session_id="s1")

    result = agent.run("use a bad tool")

    tool_traces = [t for t in store.get_task_traces(result.metadata["task_id"]) if t["kind"] == "tool_call"]
    assert len(tool_traces) == 1
    assert tool_traces[0]["ok"] == 0
    assert "unknown tool" in tool_traces[0]["error"]


def test_agent_name_is_recorded_on_traces(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    router = FakeRouter([ChatResult(provider="local", model="m", content="ok")])
    agent = ChatAgent(
        router=router, skills=make_skills(), memory=store, session_id="s1", agent_name="researcher"
    )

    result = agent.run("hi")

    assert store.get_task_traces(result.metadata["task_id"])[0]["agent"] == "researcher"


def test_curated_memory_is_injected_as_a_system_message(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    curated = CuratedMemory(base_dir=tmp_path)
    curated.add("prefers concise answers")
    router = FakeRouter([ChatResult(provider="local", model="m", content="ok")])
    agent = ChatAgent(
        router=router, skills=make_skills(), memory=store, session_id="s1", curated=curated
    )

    agent.run("hi")

    first_message = router.seen_messages[0][0]
    assert first_message["role"] == "system"
    assert "prefers concise answers" in first_message["content"]


def test_no_system_message_when_curated_memory_is_empty(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    router = FakeRouter([ChatResult(provider="local", model="m", content="ok")])
    agent = ChatAgent(
        router=router,
        skills=make_skills(),
        memory=store,
        session_id="s1",
        curated=CuratedMemory(base_dir=tmp_path),
    )

    agent.run("hi")

    assert all(m["role"] != "system" for m in router.seen_messages[0])


def test_cost_summary_groups_and_totals(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    store.append_trace(
        task_id="t1", session_id="s", kind="model_call", ok=True, agent="coder",
        latency_ms=100, prompt_tokens=10, completion_tokens=5, cost_usd=0.5,
    )
    store.append_trace(
        task_id="t2", session_id="s", kind="model_call", ok=False, agent="coder",
        latency_ms=300, cost_usd=0.25,
    )
    store.append_trace(
        task_id="t3", session_id="s", kind="model_call", ok=True, agent="researcher",
        latency_ms=50, cost_usd=0.0,
    )

    summary = {row["key"]: row for row in store.cost_summary("agent")}

    assert summary["coder"]["calls"] == 2
    assert summary["coder"]["failures"] == 1
    assert summary["coder"]["total_cost_usd"] == 0.75
    assert summary["coder"]["avg_latency_ms"] == 200
    assert summary["coder"]["total_tokens"] == 15
    assert summary["researcher"]["failures"] == 0
