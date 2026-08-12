"""Session switching and sub-agent delegation."""

from pathlib import Path

from yozhan_runtime.agents.chat_agent import MAX_DELEGATION_DEPTH, ChatAgent
from yozhan_runtime.commands import SETTING_ACTIVE, CommandContext, dispatch
from yozhan_runtime.memory.curated import CuratedMemory
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ChatResult
from yozhan_runtime.skills.manager import SkillManager

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

AGENTS = {
    "defaults": {"fallback_chain": "default"},
    "agents": {"researcher": {"fallback_chain": "default"}, "coder": {"fallback_chain": "default"}},
}
PROVIDERS = {
    "providers": {"local": {"type": "llama_cpp", "models": [{"id": "m"}], "default_model": "m"}},
    "fallback_chains": {"default": [{"provider": "local", "model": "m"}]},
}


class FakeRouter:
    def __init__(self, reply="ok"):
        self.reply = reply

    def default_local_model(self):
        return "m"

    def chat(self, provider, model, messages, tools=None, timeout=120.0):
        return ChatResult(provider="local", model="m", content=self.reply)


def skills():
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    return manager


def ctx(store, base="s1", active=None):
    return CommandContext(
        session_id=active or base,
        base_session_id=base,
        memory=store,
        skills=skills(),
        curated=CuratedMemory(base_dir=store.db_dir),
        router=FakeRouter(),
        agents_config=AGENTS,
        providers_config=PROVIDERS,
    )


# --- /session switching -----------------------------------------------------


def test_session_switch_records_against_the_base(tmp_path):
    # A channel can't change the id it sends, so the switch has to live on the
    # base id rather than on the target.
    store = SessionStore(user_id="t", db_dir=tmp_path)
    out = dispatch("/session work", ctx(store))
    assert "work" in out
    assert store.get_setting("s1", SETTING_ACTIVE) == "work"


def test_switching_back_to_the_base_clears_the_override(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    dispatch("/session work", ctx(store))
    dispatch("/session s1", ctx(store))
    assert store.get_setting("s1", SETTING_ACTIVE) is None


def test_session_list_shows_message_counts(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    store.append_message("work", "user", "a")
    store.append_message("work", "user", "b")
    store.append_message("home", "user", "c")

    out = dispatch("/session list", ctx(store))

    assert "work (2 messages)" in out
    assert "home (1 message)" in out


def test_invalid_session_names_refused(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    assert "may contain" in dispatch("/session ../escape", ctx(store))
    assert store.get_setting("s1", SETTING_ACTIVE) is None


def test_agent_reads_and_writes_the_switched_session(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    store.set_setting("s1", SETTING_ACTIVE, "work")
    agent = ChatAgent(
        router=FakeRouter("hello"),
        skills=skills(),
        memory=store,
        session_id="s1",
        curated=CuratedMemory(base_dir=tmp_path),
    )

    assert agent.active_session == "work"
    agent.run("hi")

    assert [m["content"] for m in store.get_history("work")] == ["hi", "hello"]
    assert store.get_history("s1") == []


def test_two_sessions_keep_separate_history(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    curated = CuratedMemory(base_dir=tmp_path)

    def run_in(target, text):
        store.set_setting("s1", SETTING_ACTIVE, target)
        ChatAgent(
            router=FakeRouter("reply"), skills=skills(), memory=store, session_id="s1", curated=curated
        ).run(text)

    run_in("work", "about work")
    run_in("home", "about home")

    assert [m["content"] for m in store.get_history("work")] == ["about work", "reply"]
    assert [m["content"] for m in store.get_history("home")] == ["about home", "reply"]


# --- delegation -------------------------------------------------------------


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def dispatch(self, agent_name, task, session_id=None, depth=0):
        self.calls.append((agent_name, task, session_id, depth))

        class Result:
            provider, model, error = "local", "m", None

            class result:
                output = f"{agent_name} says done"

        return Result()


def make_agent(tmp_path, orchestrator=None, depth=0, agent_name="chat"):
    return ChatAgent(
        router=FakeRouter(),
        skills=skills(),
        memory=SessionStore(user_id="t", db_dir=tmp_path),
        session_id="s1",
        curated=CuratedMemory(base_dir=tmp_path),
        agents_config=AGENTS,
        providers_config=PROVIDERS,
        orchestrator=orchestrator,
        depth=depth,
        agent_name=agent_name,
    )


def test_delegate_tool_is_absent_without_an_orchestrator(tmp_path):
    names = [t["function"]["name"] for t in make_agent(tmp_path)._all_tools()]
    assert "delegate" not in names


def test_delegate_tool_is_offered_with_an_orchestrator(tmp_path):
    agent = make_agent(tmp_path, FakeOrchestrator())
    tool = next(t for t in agent._all_tools() if t["function"]["name"] == "delegate")
    assert set(tool["function"]["parameters"]["properties"]["agent"]["enum"]) == {"researcher", "coder"}


def test_delegation_runs_the_sub_agent_and_returns_its_answer(tmp_path):
    orchestrator = FakeOrchestrator()
    agent = make_agent(tmp_path, orchestrator)

    out = agent._execute_tool("delegate", {"agent": "researcher", "task": "look it up"})

    assert "researcher says done" in out
    name, task, session_id, depth = orchestrator.calls[0]
    assert (name, task, depth) == ("researcher", "look it up", 1)
    # A sub-agent gets its own session so its turns don't pollute the parent's.
    assert session_id == "s1::researcher"


def test_delegation_stops_at_the_depth_limit(tmp_path):
    # Without this an agent could delegate to itself indefinitely, spending
    # real money doing it.
    deep = make_agent(tmp_path, FakeOrchestrator(), depth=MAX_DELEGATION_DEPTH)
    assert "delegate" not in [t["function"]["name"] for t in deep._all_tools()]


def test_an_agent_cannot_delegate_to_itself(tmp_path):
    agent = make_agent(tmp_path, FakeOrchestrator(), agent_name="researcher")
    assert "cannot delegate to itself" in agent._execute_tool(
        "delegate", {"agent": "researcher", "task": "loop"}
    )


def test_delegating_to_an_unknown_agent_is_refused(tmp_path):
    agent = make_agent(tmp_path, FakeOrchestrator())
    out = agent._execute_tool("delegate", {"agent": "nobody", "task": "x"})
    assert "no agent named 'nobody'" in out and "researcher" in out


def test_delegate_requires_both_arguments(tmp_path):
    agent = make_agent(tmp_path, FakeOrchestrator())
    assert "needs both" in agent._execute_tool("delegate", {"agent": "researcher"})


def test_a_failing_sub_agent_is_reported_not_raised(tmp_path):
    class Failing(FakeOrchestrator):
        def dispatch(self, *a, **k):
            raise RuntimeError("sub-agent exploded")

    agent = make_agent(tmp_path, Failing())
    out = agent._execute_tool("delegate", {"agent": "researcher", "task": "x"})
    assert out.startswith("error delegating") and "exploded" in out
