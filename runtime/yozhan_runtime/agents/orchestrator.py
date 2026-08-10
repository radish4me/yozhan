"""Orchestrator: resolves a task to one or more configured agents and runs
each through ChatAgent using that agent's independently-resolved model
assignment (config/agents.yaml + config/providers.yaml — see resolve.py and
ARCHITECTURE.md section 4.2). One agent's failure (e.g. a provider with no
transport yet, see providers/router.py) never sinks the others in a
multi-agent dispatch. Real parallel execution and cross-provider fallback
walking land in Phase 4; today's dispatch is sequential.
"""

from __future__ import annotations

from dataclasses import dataclass

from yozhan_runtime.agents.base import AgentResult
from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.agents.resolve import resolve_agent
from yozhan_runtime.config import load_agents, load_providers
from yozhan_runtime.memory.store import MemoryBackend
from yozhan_runtime.providers.router import ProviderRouter
from yozhan_runtime.skills.manager import SkillManager


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
    ):
        self.router = router
        self.skills = skills
        self.memory = memory
        self._agents_config = agents_config if agents_config is not None else load_agents()
        self._providers_config = providers_config if providers_config is not None else load_providers()

    def dispatch(self, agent_name: str, task: str, session_id: str | None = None) -> DispatchResult:
        resolved = resolve_agent(agent_name, self._agents_config, self._providers_config)
        agent = ChatAgent(
            router=self.router,
            skills=self.skills,
            memory=self.memory,
            session_id=session_id or agent_name,
            provider=resolved.provider,
            model=resolved.model,
        )
        try:
            result = agent.run(task)
            return DispatchResult(agent=agent_name, provider=resolved.provider, model=resolved.model, result=result)
        except Exception as exc:  # one agent's failure shouldn't sink a multi-agent dispatch
            return DispatchResult(
                agent=agent_name, provider=resolved.provider, model=resolved.model, result=None, error=str(exc)
            )

    def dispatch_many(self, assignments: list[tuple[str, str]]) -> list[DispatchResult]:
        """assignments: list of (agent_name, task) pairs. Sequential today;
        Phase 4 adds real concurrent fan-out for `mode: parallel` chains."""
        return [self.dispatch(agent_name, task) for agent_name, task in assignments]
