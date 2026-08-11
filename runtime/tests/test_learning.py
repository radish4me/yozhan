import pytest

from yozhan_runtime.learning.reviewer import (
    LearningReviewer,
    analyze_traces,
    apply_proposal,
    parse_skill_document,
    reviewer_from_config,
)
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ChatResult

VALID_SKILL = """---
name: deploy-check
version: 0.1.0
description: Verify a deploy succeeded.
capabilities: [ops]
tags: [ops]
depends_on: []
---

# deploy-check

1. Read the deploy log.
2. Confirm the health endpoint returns 200.
"""


class FakeRouter:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat(self, provider, model, messages, tools=None, timeout=120.0):
        self.calls += 1
        return ChatResult(provider=provider, model=model, content=self.reply)

    def chat_with_fallback(self, chain, messages, tools=None, timeout=120.0):
        self.calls += 1
        return ChatResult(provider="local", model="m", content=self.reply)


def traces(tool_calls: int, failures: int = 0) -> list[dict]:
    out = [{"kind": "model_call", "name": "m", "ok": 1}]
    for i in range(tool_calls):
        out.append({"kind": "tool_call", "name": f"tool_{i}", "ok": 0 if i < failures else 1})
    return out


# --- trace analysis ---------------------------------------------------------


def test_trivial_task_does_not_qualify():
    assert not analyze_traces(traces(tool_calls=1)).qualifies


def test_multi_tool_task_qualifies():
    signals = analyze_traces(traces(tool_calls=3))
    assert signals.qualifies
    assert signals.tool_calls == 3
    assert "3 tool calls" in signals.reasons[0]


def test_error_recovery_qualifies_below_the_tool_threshold():
    signals = analyze_traces(traces(tool_calls=2, failures=1))
    assert signals.qualifies
    assert any("recovered" in r for r in signals.reasons)


def test_distinct_tools_are_deduplicated():
    repeated = [{"kind": "tool_call", "name": "same", "ok": 1} for _ in range(4)]
    assert analyze_traces(repeated).distinct_tools == ["same"]


# --- skill document parsing -------------------------------------------------


def test_parses_a_valid_skill_document():
    parsed = parse_skill_document(VALID_SKILL)
    assert parsed is not None
    assert parsed[0] == "deploy-check"


def test_skip_response_yields_nothing():
    assert parse_skill_document("SKIP") is None


def test_strips_a_markdown_code_fence():
    fenced = "```markdown\n" + VALID_SKILL + "\n```"
    parsed = parse_skill_document(fenced)
    assert parsed is not None and parsed[0] == "deploy-check"


def test_rejects_document_without_frontmatter():
    assert parse_skill_document("# just a heading\n\nsome prose") is None


def test_rejects_missing_description():
    assert parse_skill_document("---\nname: x\n---\n\nbody") is None


@pytest.mark.parametrize("bad_name", ["../escape", "has space", "Upper", "/abs", "..", "a/b"])
def test_rejects_unsafe_skill_names(bad_name):
    # The name becomes a directory under skills/ — a traversal here would let a
    # model-authored proposal write outside the skills tree.
    doc = f"---\nname: {bad_name}\ndescription: d\n---\n\nbody"
    assert parse_skill_document(doc) is None


# --- reviewer end to end ----------------------------------------------------


def test_reviewer_stages_a_proposal_for_a_qualifying_task(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    for i in range(3):
        store.append_trace(task_id="task1", session_id="s1", kind="tool_call", name=f"t{i}", ok=True)
    store.append_message("s1", "user", "do the thing")

    reviewer = LearningReviewer(store, FakeRouter(VALID_SKILL))
    proposal_id = reviewer.review_task("task1", "s1")

    assert proposal_id is not None
    pending = store.list_proposals("pending")
    assert len(pending) == 1
    assert pending[0]["skill_name"] == "deploy-check"
    assert pending[0]["action"] == "create"


def test_reviewer_skips_a_trivial_task_without_calling_the_model(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    store.append_trace(task_id="task1", session_id="s1", kind="model_call", name="m", ok=True)

    router = FakeRouter(VALID_SKILL)
    assert LearningReviewer(store, router).review_task("task1", "s1") is None
    assert router.calls == 0  # no model spend on tasks that can't teach anything


def test_reviewer_marks_a_known_skill_as_a_patch(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    for i in range(3):
        store.append_trace(task_id="task1", session_id="s1", kind="tool_call", name=f"t{i}", ok=True)

    reviewer = LearningReviewer(store, FakeRouter(VALID_SKILL))
    reviewer.review_task("task1", "s1", existing_skills=["deploy-check"])
    assert store.list_proposals("pending")[0]["action"] == "patch"


def test_reviewer_discards_an_unparseable_model_reply(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    for i in range(3):
        store.append_trace(task_id="task1", session_id="s1", kind="tool_call", name=f"t{i}", ok=True)

    reviewer = LearningReviewer(store, FakeRouter("sure, here's an idea: do it faster"))
    assert reviewer.review_task("task1", "s1") is None
    assert store.list_proposals("pending") == []


# --- approval / application -------------------------------------------------


def test_approving_writes_the_skill_and_marks_it_approved(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    proposal_id = store.add_proposal("create", "deploy-check", VALID_SKILL, "because")

    written = apply_proposal(store, proposal_id, tmp_path / "skills")

    assert written == tmp_path / "skills" / "deploy-check" / "SKILL.md"
    assert "deploy-check" in written.read_text(encoding="utf-8")
    assert store.list_proposals("pending") == []
    assert store.get_proposal(proposal_id)["status"] == "approved"


def test_cannot_apply_the_same_proposal_twice(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    proposal_id = store.add_proposal("create", "deploy-check", VALID_SKILL, "because")
    apply_proposal(store, proposal_id, tmp_path / "skills")
    with pytest.raises(ValueError, match="already approved"):
        apply_proposal(store, proposal_id, tmp_path / "skills")


def test_apply_refuses_an_unsafe_stored_name(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    proposal_id = store.add_proposal("create", "../escape", VALID_SKILL, "because")
    with pytest.raises(ValueError, match="unsafe skill name"):
        apply_proposal(store, proposal_id, tmp_path / "skills")


def test_rejecting_removes_it_from_pending(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    proposal_id = store.add_proposal("create", "deploy-check", VALID_SKILL, "because")
    store.set_proposal_status(proposal_id, "rejected")
    assert store.list_proposals("pending") == []
    assert len(store.list_proposals("rejected")) == 1


# --- config wiring ----------------------------------------------------------


def test_reviewer_from_config_returns_none_when_learning_disabled(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    assert reviewer_from_config(store, FakeRouter(""), {"learning": {"enabled": False}}, {}) is None


def test_reviewer_from_config_resolves_its_fallback_chain(tmp_path):
    store = SessionStore(user_id="t", db_dir=tmp_path)
    agents = {"learning": {"enabled": True, "fallback_chain": "local_first", "min_tool_calls": 7}}
    providers = {"fallback_chains": {"local_first": [{"provider": "local", "model": "qwen3.5-0.8b"}]}}

    reviewer = reviewer_from_config(store, FakeRouter(""), agents, providers)

    assert reviewer is not None
    assert reviewer.chain == [{"provider": "local", "model": "qwen3.5-0.8b"}]
    assert reviewer.min_tool_calls == 7
