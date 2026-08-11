"""The self-improving loop: after a task finishes, look at what it actually
took (the trace log), and if it was non-trivial enough to be worth
remembering *as a procedure*, ask a model to write it up as a SKILL.md —
either a new skill or a patch to an existing one.

Nothing is written to disk here. Proposals are staged in the store and
applied only through apply_proposal(), which the CLI gates behind
`learning.write_approval` (default true). An agent that silently rewrites
its own instruction set is a debugging nightmare and a security problem;
approval is the default for that reason, not an afterthought.

See ROADMAP.md Phase 6 and ARCHITECTURE.md section 3.4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from yozhan_runtime.memory.store import SessionStore

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

DEFAULT_MIN_TOOL_CALLS = 3


@dataclass
class TaskSignals:
    """Why (or why not) a finished task is worth learning from."""

    tool_calls: int = 0
    failures: int = 0
    distinct_tools: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def qualifies(self) -> bool:
        return bool(self.reasons)


def analyze_traces(traces: list[dict], min_tool_calls: int = DEFAULT_MIN_TOOL_CALLS) -> TaskSignals:
    """A task is worth learning from when it was procedurally interesting:
    it took several tool calls, or it recovered from a failure. A one-shot
    Q&A teaches nothing reusable."""
    signals = TaskSignals()
    tools_seen: list[str] = []

    for trace in traces:
        if trace.get("kind") == "tool_call":
            signals.tool_calls += 1
            name = trace.get("name")
            if name and name not in tools_seen:
                tools_seen.append(name)
        if not trace.get("ok"):
            signals.failures += 1

    signals.distinct_tools = tools_seen

    if signals.tool_calls >= min_tool_calls:
        signals.reasons.append(f"used {signals.tool_calls} tool calls (threshold {min_tool_calls})")
    if signals.failures and signals.tool_calls:
        signals.reasons.append(f"recovered from {signals.failures} failure(s)")

    return signals


def _transcript(store: SessionStore, session_id: str, limit: int = 20) -> str:
    history = store.get_history(session_id, limit=limit)
    return "\n".join(f"{m['role']}: {m['content']}" for m in history)


def _build_prompt(signals: TaskSignals, transcript: str, existing_skills: list[str]) -> list[dict]:
    known = ", ".join(existing_skills) if existing_skills else "(none)"
    return [
        {
            "role": "system",
            "content": (
                "You write reusable agent skills in the agentskills.io SKILL.md format. "
                "Given a transcript of a task the agent just completed, decide whether the "
                "*procedure* is worth capturing so the next attempt is faster.\n\n"
                "Reply with ONLY a SKILL.md document: YAML frontmatter delimited by --- lines "
                "(keys: name, version, description, capabilities, tags, depends_on) followed by "
                "a markdown body describing the procedure as numbered steps.\n"
                "The name must be lowercase-kebab-case.\n"
                "If the task is too trivial or too specific to generalize, reply with exactly: SKIP"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Existing skills (patch one of these instead of duplicating it, by reusing its name): {known}\n"
                f"Why this task was flagged: {'; '.join(signals.reasons)}\n"
                f"Tools used: {', '.join(signals.distinct_tools) or '(none)'}\n\n"
                f"Transcript:\n{transcript}"
            ),
        },
    ]


def parse_skill_document(text: str) -> tuple[str, str] | None:
    """Validates a model-authored SKILL.md. Returns (skill_name, document) or
    None if it isn't a well-formed, safely-named skill."""
    text = text.strip()
    if text.startswith("```"):  # strip a markdown code fence if the model added one
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    if not text or text.upper().startswith("SKIP"):
        return None

    match = _FRONTMATTER_RE.match(text + "\n")
    if not match:
        return None
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None

    name = frontmatter.get("name")
    # The name becomes a directory under skills/ — reject anything that isn't a
    # plain kebab-case token so a proposal can't traverse out of the skills dir.
    if not isinstance(name, str) or not _SKILL_NAME_RE.match(name):
        return None
    if not frontmatter.get("description"):
        return None
    return name, text


class LearningReviewer:
    def __init__(
        self,
        store: SessionStore,
        router,
        chain: list[dict] | None = None,
        provider: str = "local",
        model: str | None = None,
        min_tool_calls: int = DEFAULT_MIN_TOOL_CALLS,
    ):
        self.store = store
        self.router = router
        self.chain = chain
        self.provider = provider
        self.model = model
        self.min_tool_calls = min_tool_calls

    def _call_model(self, messages: list[dict]):
        if self.chain:
            return self.router.chat_with_fallback(self.chain, messages)
        return self.router.chat(self.provider, self.model, messages)

    def review_task(
        self, task_id: str, session_id: str, existing_skills: list[str] | None = None
    ) -> int | None:
        """Returns the staged proposal's id, or None if the task didn't
        qualify or the model declined to write a skill."""
        traces = self.store.get_task_traces(task_id)
        signals = analyze_traces(traces, self.min_tool_calls)
        if not signals.qualifies:
            return None

        existing_skills = existing_skills or []
        messages = _build_prompt(signals, _transcript(self.store, session_id), existing_skills)
        result = self._call_model(messages)
        parsed = parse_skill_document(result.content or "")
        if parsed is None:
            return None

        skill_name, document = parsed
        action = "patch" if skill_name in existing_skills else "create"
        return self.store.add_proposal(
            action=action,
            skill_name=skill_name,
            content=document,
            rationale="; ".join(signals.reasons),
            task_id=task_id,
        )


def reviewer_from_config(
    store: SessionStore, router, agents_config: dict, providers_config: dict
) -> LearningReviewer | None:
    """Builds a reviewer from the `learning:` block in config/agents.yaml,
    or None when learning is disabled."""
    learning = agents_config.get("learning") or {}
    if not learning.get("enabled", False):
        return None

    chain = None
    chain_name = learning.get("fallback_chain")
    if chain_name:
        chain_def = (providers_config.get("fallback_chains") or {}).get(chain_name)
        if isinstance(chain_def, dict):  # a parallel chain makes no sense for a background reviewer
            chain_def = chain_def.get("members")
        chain = chain_def or None

    return LearningReviewer(
        store=store,
        router=router,
        chain=chain,
        provider=learning.get("provider", "local"),
        model=learning.get("model"),
        min_tool_calls=learning.get("min_tool_calls", DEFAULT_MIN_TOOL_CALLS),
    )


def apply_proposal(store: SessionStore, proposal_id: int, skills_dir: Path) -> Path:
    """Writes an approved proposal to disk as skills/<name>/SKILL.md and marks
    it approved. Raises if the proposal is missing or not pending."""
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"no proposal with id {proposal_id}")
    if proposal["status"] != "pending":
        raise ValueError(f"proposal {proposal_id} is already {proposal['status']}")

    name = proposal["skill_name"]
    if not _SKILL_NAME_RE.match(name):
        raise ValueError(f"refusing to write unsafe skill name {name!r}")

    target_dir = skills_dir / name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    target.write_text(proposal["content"].rstrip() + "\n", encoding="utf-8")
    store.set_proposal_status(proposal_id, "approved")
    return target
