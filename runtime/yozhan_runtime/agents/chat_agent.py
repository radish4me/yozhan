"""ChatAgent: the concrete BaseAgent every named agent in config/agents.yaml
runs as. Runs a tool-calling loop against its resolved model assignment —
either a direct (provider, model) pin or a sequential fallback `chain`
(see resolve.py) — backed by SkillManager (callable tools) and a
MemoryBackend (persisted conversation history).

Phase 6 additions: curated cross-session memory is injected as a system
message at session start, and every model call and tool call is timed and
written to the trace log, which is what the learning loop reviews and the
Phase 7 cost/latency report aggregates.

See ARCHITECTURE.md sections 3.2-3.4.
"""

from __future__ import annotations

import json
import time
from uuid import uuid4

from yozhan_runtime.agents.base import AgentResult, BaseAgent
from yozhan_runtime.memory.curated import CuratedMemory
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
        agent_name: str | None = None,
        curated: CuratedMemory | None = None,
    ):
        self.router = router
        self.skills = skills
        self.memory = memory
        self.session_id = session_id
        self.provider = provider
        self.model = model
        self.chain = chain
        self.max_tool_iterations = max_tool_iterations
        self.agent_name = agent_name or self.name
        self.curated = curated
        self.last_task_id: str | None = None

    def _call_model(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        if self.chain:
            return self.router.chat_with_fallback(self.chain, messages, tools=tools or None)
        return self.router.chat(self.provider, self.model, messages, tools=tools or None)

    def _build_messages(self) -> list[dict]:
        messages: list[dict] = []
        if self.curated is not None:
            preamble = self.curated.as_system_prompt()
            if preamble:
                messages.append({"role": "system", "content": preamble})
        messages.extend(self.memory.get_history(self.session_id))
        return messages

    def _trace(self, task_id: str, kind: str, ok: bool, **fields) -> None:
        self.memory.append_trace(
            task_id=task_id,
            session_id=self.session_id,
            agent=self.agent_name,
            kind=kind,
            ok=ok,
            **fields,
        )

    def run(self, task: str, context: dict | None = None) -> AgentResult:
        task_id = uuid4().hex
        self.last_task_id = task_id

        self.memory.append_message(self.session_id, "user", task)
        messages = self._build_messages()
        tools = self.skills.as_openai_tools()

        for _ in range(self.max_tool_iterations):
            started = time.monotonic()
            try:
                result = self._call_model(messages, tools)
            except Exception as exc:
                self._trace(
                    task_id,
                    "model_call",
                    ok=False,
                    name=self.model,
                    provider=self.provider,
                    latency_ms=(time.monotonic() - started) * 1000,
                    error=str(exc),
                )
                raise

            usage = result.usage or {}
            self._trace(
                task_id,
                "model_call",
                ok=True,
                name=result.model,
                provider=result.provider,
                latency_ms=(time.monotonic() - started) * 1000,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                cost_usd=result.cost_usd,
            )

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

                    tool_started = time.monotonic()
                    output = self.skills.execute(function["name"], arguments)
                    # SkillManager.execute never raises — it returns an "error: ..."
                    # string so one bad tool can't kill the loop. Detect that here
                    # so the trace log reflects real failures.
                    failed = output.startswith("error")
                    self._trace(
                        task_id,
                        "tool_call",
                        ok=not failed,
                        name=function["name"],
                        latency_ms=(time.monotonic() - tool_started) * 1000,
                        error=output if failed else None,
                    )
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
                continue

            content = result.content or ""
            self.memory.append_message(self.session_id, "assistant", content)
            return AgentResult(
                output=content,
                metadata={"provider": result.provider, "model": result.model, "task_id": task_id},
            )

        fallback = "Reached the tool-call limit for this turn without a final answer — try rephrasing."
        self.memory.append_message(self.session_id, "assistant", fallback)
        return AgentResult(output=fallback, metadata={"truncated": True, "task_id": task_id})
