"""ChatAgent: the concrete BaseAgent every named agent in config/agents.yaml
runs as. Runs a tool-calling loop against its resolved model assignment —
either a direct (provider, model) pin or a sequential fallback `chain`
(ROADMAP.md Phase 4; see resolve.py) — backed by SkillManager (callable
tools) and a MemoryBackend (persisted conversation history).
See ARCHITECTURE.md sections 3.2-3.4.
"""

from __future__ import annotations

import json

from yozhan_runtime.agents.base import AgentResult, BaseAgent
from yozhan_runtime.memory.store import MemoryBackend
from yozhan_runtime.providers.router import ChatResult, ProviderRouter
from yozhan_runtime.skills.manager import SkillManager


class ChatAgent(BaseAgent):
    name = "chat"
    mode = "on-demand"

    def __init__(
        self,
        router: ProviderRouter,
        skills: SkillManager,
        memory: MemoryBackend,
        session_id: str = "default",
        provider: str = "local",
        model: str | None = None,
        chain: list[dict] | None = None,
        max_tool_iterations: int = 5,
    ):
        self.router = router
        self.skills = skills
        self.memory = memory
        self.session_id = session_id
        self.provider = provider
        self.model = model
        self.chain = chain
        self.max_tool_iterations = max_tool_iterations

    def _call_model(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        if self.chain:
            return self.router.chat_with_fallback(self.chain, messages, tools=tools or None)
        return self.router.chat(self.provider, self.model, messages, tools=tools or None)

    def run(self, task: str, context: dict | None = None) -> AgentResult:
        self.memory.append_message(self.session_id, "user", task)
        messages = self.memory.get_history(self.session_id)
        tools = self.skills.as_openai_tools()

        for _ in range(self.max_tool_iterations):
            result = self._call_model(messages, tools)

            if result.tool_calls:
                messages.append(
                    {"role": "assistant", "content": result.content or "", "tool_calls": result.tool_calls}
                )
                for call in result.tool_calls:
                    function = call["function"]
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    output = self.skills.execute(function["name"], arguments)
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
                continue

            content = result.content or ""
            self.memory.append_message(self.session_id, "assistant", content)
            return AgentResult(output=content, metadata={"provider": result.provider, "model": result.model})

        fallback = "Reached the tool-call limit for this turn without a final answer — try rephrasing."
        self.memory.append_message(self.session_id, "assistant", fallback)
        return AgentResult(output=fallback, metadata={"truncated": True})
