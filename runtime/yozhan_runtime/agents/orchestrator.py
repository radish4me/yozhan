"""Orchestrator: resolves a task to one or more configured agents and runs
each through its own resolved model assignment (config/agents.yaml +
config/providers.yaml — see resolve.py, ARCHITECTURE.md section 4.2).

Agents with a sequential chain (a direct pin or a fallback_chain) get
automatic fallback-on-failure via ChatAgent + ProviderRouter.chat_with_fallback
(ROADMAP.md Phase 4). Agents with a `mode: parallel` chain fan out
concurrently via ProviderRouter.chat_parallel() and their per-model outputs
are combined into one labeled result. One agent's failure never sinks the
others in a multi-agent dispatch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yozhan_runtime.agents.base import AgentResult
from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.agents.resolve import ResolvedAgent, resolve_agent
from yozhan_runtime.config import load_agents, load_providers
from yozhan_runtime.memory.curated import CuratedMemory
from yozhan_runtime.memory.store import MemoryBackend
from yozhan_runtime.providers.router import ProviderRouter
from yozhan_runtime.skills.manager import SkillManager

if TYPE_CHECKING:
    from yozhan_runtime.learning.reviewer import LearningReviewer

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    agent: str
    provider: str
    model: str
    result: AgentResult | None
    error: str | None = None


class Orchestrator:
    def __init__(
        self,
        router: ProviderRouter,
        skills: SkillManager,
        memory: MemoryBackend,
        agents_config: dict | None = None,
        providers_config: dict | None = None,
        curated: CuratedMemory | None = None,
        reviewer: "LearningReviewer | None" = None,
    ):
        self.router = router
        self.skills = skills
        self.memory = memory
        self._agents_config = agents_config if agents_config is not None else load_agents()
        self._providers_config = providers_config if providers_config is not None else load_providers()
        self.curated = curated
        self.reviewer = reviewer

    @property
    def learning_config(self) -> dict:
        return self._agents_config.get("learning", {}) or {}

    def dispatch(self, agent_name: str, task: str, session_id: str | None = None) -> DispatchResult:
        resolved = resolve_agent(agent_name, self._agents_config, self._providers_config)
        session_id = session_id or agent_name
        if resolved.parallel_members:
            return self._dispatch_parallel(agent_name, resolved, task, session_id)
        return self._dispatch_sequential(agent_name, resolved, task, session_id)

    def _dispatch_sequential(
        self, agent_name: str, resolved: ResolvedAgent, task: str, session_id: str
    ) -> DispatchResult:
        agent = ChatAgent(
            router=self.router,
            skills=self.skills,
            memory=self.memory,
            session_id=session_id,
            chain=resolved.chain,
            agent_name=agent_name,
            curated=self.curated,
        )
        try:
            result = agent.run(task)
            self.maybe_review(result.metadata.get("task_id"), session_id)
            return DispatchResult(agent=agent_name, provider=resolved.provider, model=resolved.model, result=result)
        except Exception as exc:  # one agent's failure shouldn't sink a multi-agent dispatch
            return DispatchResult(
                agent=agent_name, provider=resolved.provider, model=resolved.model, result=None, error=str(exc)
            )

    def _dispatch_parallel(
        self, agent_name: str, resolved: ResolvedAgent, task: str, session_id: str
    ) -> DispatchResult:
        self.memory.append_message(session_id, "user", task)
        messages = self.memory.get_history(session_id)
        tools = self.skills.as_openai_tools()
        outcomes = self.router.chat_parallel(resolved.parallel_members, messages, tools=tools or None)

        lines: list[str] = []
        per_model: list[dict] = []
        any_success = False
        for outcome in outcomes:
            tag = f"{outcome['provider']}/{outcome['model']}"
            if outcome["error"]:
                lines.append(f"[{tag}] error: {outcome['error']}")
            else:
                any_success = True
                lines.append(f"[{tag}] {outcome['result'].content}")
            per_model.append({"provider": outcome["provider"], "model": outcome["model"], "error": outcome["error"]})

        combined = "\n".join(lines)
        self.memory.append_message(session_id, "assistant", combined)

        if not any_success:
            errors = "; ".join(o["error"] for o in outcomes if o["error"])
            return DispatchResult(
                agent=agent_name,
                provider=resolved.provider,
                model=resolved.model,
                result=None,
                error=f"all parallel members failed: {errors}",
            )
        return DispatchResult(
            agent=agent_name,
            provider=resolved.provider,
            model=resolved.model,
            result=AgentResult(output=combined, metadata={"parallel": per_model}),
        )

    def maybe_review(self, task_id: str | None, session_id: str) -> int | None:
        """Hands a finished task to the learning reviewer, if one is configured
        and enabled. Returns a staged proposal id, or None.

        Reviewing is strictly best-effort: a failure here (reviewer model
        down, malformed proposal) must never turn a successful task into a
        failed one, so everything is swallowed and logged."""
        if task_id is None or self.reviewer is None:
            return None
        if not self.learning_config.get("enabled", False):
            return None
        try:
            existing = [s.name for s in self.skills.discovered()]
            return self.reviewer.review_task(task_id, session_id, existing_skills=existing)
        except Exception as exc:
            logger.warning("learning review failed for task %s: %s", task_id, exc)
            return None

    def dispatch_many(self, assignments: list[tuple[str, str]]) -> list[DispatchResult]:
        """assignments: list of (agent_name, task) pairs."""
        return [self.dispatch(agent_name, task) for agent_name, task in assignments]
