from pathlib import Path

import pytest

from yozhan_runtime.commands import (
    SETTING_MODEL,
    CommandContext,
    dispatch,
    is_command,
    parse,
)
from yozhan_runtime.memory.curated import CuratedMemory
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.skills.manager import SkillManager

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

PROVIDERS = {
    "providers": {
        "local": {
            "type": "llama_cpp",
            "models": [{"id": "qwen3.5-0.8b"}, {"id": "lfm2.5"}],
            "default_model": "qwen3.5-0.8b",
        }
    },
    "fallback_chains": {"default": [{"provider": "local", "model": "qwen3.5-0.8b"}]},
}
AGENTS = {"defaults": {"fallback_chain": "default"}, "agents": {"researcher": {"fallback_chain": "default"}}}


class FakeRouter:
    def default_local_model(self):
        return "qwen3.5-0.8b"


def make_ctx(tmp_path, mcp=None) -> CommandContext:
    skills = SkillManager([REPO_SKILLS_DIR])
    skills.discover()
    return CommandContext(
        session_id="s1",
        memory=SessionStore(user_id="t", db_dir=tmp_path),
        skills=skills,
        curated=CuratedMemory(base_dir=tmp_path),
        router=FakeRouter(),
        agents_config=AGENTS,
        providers_config=PROVIDERS,
        mcp=mcp,
    )


# --- recognition ------------------------------------------------------------


@pytest.mark.parametrize("text", ["/help", "/model gpt", "  /new  ", "/MCP"])
def test_recognised_as_commands(text):
    assert is_command(text)


@pytest.mark.parametrize(
    "text",
    [
        "hello",
        "",
        "/",
        "//",
        "/etc/hosts is a file",  # a path, not a command
        "what is 1/2",
        "/123",
    ],
)
def test_not_commands(text):
    # Ordinary messages that happen to contain a slash must reach the model.
    assert not is_command(text)


def test_parse_splits_name_and_args():
    assert parse("/model qwen3.5-0.8b") == ("model", ["qwen3.5-0.8b"])
    assert parse("/remember likes short answers") == ("remember", ["likes", "short", "answers"])


def test_parse_respects_quotes():
    assert parse('/remember "two words together"') == ("remember", ["two words together"])


def test_parse_tolerates_an_unbalanced_quote():
    # shlex raises on this; a user typo shouldn't be an exception.
    name, args = parse('/remember "unclosed')
    assert name == "remember"


# --- dispatch ---------------------------------------------------------------


def test_unknown_command_suggests_something(tmp_path):
    out = dispatch("/hel", make_ctx(tmp_path))
    assert "Unknown command" in out and "/help" in out


def test_help_lists_every_command(tmp_path):
    out = dispatch("/help", make_ctx(tmp_path))
    for expected in ["/new", "/model", "/skills", "/mcp", "/search", "/costs"]:
        assert expected in out


def test_aliases_work(tmp_path):
    assert "Cleared" in dispatch("/clear", make_ctx(tmp_path))
    assert "Available commands" in dispatch("/?", make_ctx(tmp_path))


def test_a_failing_command_returns_an_error_not_an_exception(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.memory = object()  # missing every method a command needs
    out = dispatch("/session", ctx)
    assert out.startswith("error running /session")


# --- specific commands ------------------------------------------------------


def test_new_clears_history_but_keeps_traces(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.memory.append_message("s1", "user", "hello")
    ctx.memory.append_trace(task_id="t1", session_id="s1", kind="model_call", ok=True)

    dispatch("/new", ctx)

    assert ctx.memory.get_history("s1") == []
    # Traces are the record of what happened and feed the learning loop.
    assert len(ctx.memory.get_task_traces("t1")) == 1


def test_new_only_clears_its_own_session(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.memory.append_message("s1", "user", "mine")
    ctx.memory.append_message("other", "user", "theirs")

    dispatch("/new", ctx)

    assert ctx.memory.get_history("other") == [{"role": "user", "content": "theirs"}]


def test_model_shows_the_default_when_unset(tmp_path):
    assert "qwen3.5-0.8b" in dispatch("/model", make_ctx(tmp_path))


def test_model_sets_a_session_override(tmp_path):
    ctx = make_ctx(tmp_path)
    out = dispatch("/model lfm2.5", ctx)
    assert "lfm2.5" in out
    assert ctx.memory.get_setting("s1", SETTING_MODEL) == "lfm2.5"


def test_model_warns_about_an_unknown_id_but_still_sets_it(tmp_path):
    # providers.yaml may list remote models this doesn't enumerate, so refusing
    # outright would block a legitimate choice.
    ctx = make_ctx(tmp_path)
    out = dispatch("/model claude-sonnet-5", ctx)
    assert "isn't one of the configured local models" in out
    assert ctx.memory.get_setting("s1", SETTING_MODEL) == "claude-sonnet-5"


def test_model_default_clears_the_override(tmp_path):
    ctx = make_ctx(tmp_path)
    dispatch("/model lfm2.5", ctx)
    dispatch("/model default", ctx)
    assert ctx.memory.get_setting("s1", SETTING_MODEL) is None


def test_model_override_is_per_session(tmp_path):
    ctx = make_ctx(tmp_path)
    dispatch("/model lfm2.5", ctx)
    assert ctx.memory.get_setting("other", SETTING_MODEL) is None


def test_models_lists_configured_models(tmp_path):
    out = dispatch("/models", make_ctx(tmp_path))
    assert "qwen3.5-0.8b" in out and "lfm2.5" in out


def test_agents_shows_resolution(tmp_path):
    out = dispatch("/agents", make_ctx(tmp_path))
    assert "researcher" in out and "local/qwen3.5-0.8b" in out


def test_skills_and_tools_list_real_entries(tmp_path):
    ctx = make_ctx(tmp_path)
    assert "read-file" in dispatch("/skills", ctx)
    assert "read_file" in dispatch("/tools", ctx)


def test_remember_and_memory_round_trip(tmp_path):
    ctx = make_ctx(tmp_path)
    dispatch("/remember prefers short answers", ctx)
    assert "prefers short answers" in dispatch("/memory", ctx)


def test_forget_removes_a_note(tmp_path):
    ctx = make_ctx(tmp_path)
    dispatch("/remember prefers short answers", ctx)
    dispatch("/forget short", ctx)
    assert "prefers short answers" not in dispatch("/memory", ctx)


def test_search_finds_past_messages(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.memory.append_message("old", "user", "the deploy key rotation plan")
    out = dispatch("/search rotation", ctx)
    assert "rotation" in out


def test_search_without_a_query_shows_usage(tmp_path):
    assert "Usage:" in dispatch("/search", make_ctx(tmp_path))


def test_costs_reports_nothing_when_empty(tmp_path):
    assert "No traces" in dispatch("/costs", make_ctx(tmp_path))


def test_skill_new_returns_a_template_without_writing_it(tmp_path):
    # Creating executable instructions from a chat message with no review is
    # how an assistant quietly acquires behaviour nobody chose.
    ctx = make_ctx(tmp_path)
    out = dispatch("/skill new deploy-check", ctx)
    assert "name: deploy-check" in out
    assert not (tmp_path / "deploy-check").exists()


def test_mcp_says_so_when_unconfigured(tmp_path):
    assert "not configured" in dispatch("/mcp", make_ctx(tmp_path))


class FakeMCP:
    configs = [object()]

    def describe(self):
        return [
            {"name": "files", "connected": True, "error": None, "tools": ["read", "write"]},
            {"name": "broken", "connected": False, "error": "command not found", "tools": []},
        ]

    def as_openai_tools(self):
        return [{"function": {"name": "mcp__files__read"}}]


def test_mcp_reports_connected_and_failed_servers(tmp_path):
    out = dispatch("/mcp", make_ctx(tmp_path, mcp=FakeMCP()))
    assert "files: connected" in out and "read, write" in out
    assert "broken: NOT CONNECTED" in out and "command not found" in out


def test_tools_includes_mcp_tools(tmp_path):
    out = dispatch("/tools", make_ctx(tmp_path, mcp=FakeMCP()))
    assert "mcp__files__read" in out
