"""ChatAgent: Phase 2's concrete BaseAgent. Runs a tool-calling loop against
the local model, backed by SkillManager (callable tools) and a MemoryBackend
(persisted conversation history). See ARCHITECTURE.md sections 3.2-3.4.
"""

from __future__ import annotations

import json

from yozhan_runtime.agents.base import AgentResult, BaseAgent
from yozhan_runtime.memory.store import MemoryBackend
from yozhan_runtime.providers.router import ProviderRouter
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
        model: str | None = None,
        max_tool_iterations: int = 5,
    ):
        self.router = router
        self.skills = skills
        self.memory = memory
        self.session_id = session_id
        self.model = model
        self.max_tool_iterations = max_tool_iterations

    def run(self, task: str, context: dict | None = None) -> AgentResult:
        self.memory.append_message(self.session_id, "user", task)
        messages = self.memory.get_history(self.session_id)
        tools = self.skills.as_openai_tools()

        for _ in range(self.max_tool_iterations):
            result = self.router.chat_local(messages, model=self.model, tools=tools or None)

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
