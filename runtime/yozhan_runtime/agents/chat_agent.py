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

# How many times an agent may delegate onward before the chain is cut.
MAX_DELEGATION_DEPTH = 3

from yozhan_runtime.agents.base import AgentResult, BaseAgent
from yozhan_runtime.commands import (
    SETTING_ACTIVE,
    SETTING_MODEL,
    SETTING_PROVIDER,
    CommandContext,
    dispatch,
    is_command,
)
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
        mcp=None,
        agents_config: dict | None = None,
        providers_config: dict | None = None,
        orchestrator=None,
        depth: int = 0,
        config_store=None,
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
        self.mcp = mcp
        self.agents_config = agents_config or {}
        self.providers_config = providers_config or {}
        self.orchestrator = orchestrator
        self.depth = depth
        self.config_store = config_store
        self.base_session_id = session_id
        self.last_task_id: str | None = None

    @property
    def active_session(self) -> str:
        """The session in use, honouring a /session switch.

        The switch is recorded against the surface's own id, because a channel
        cannot change the id it sends — a Telegram chat is always
        `telegram:<chat id>`.
        """
        getter = getattr(self.memory, "get_setting", None)
        if getter is None:
            return self.base_session_id
        return getter(self.base_session_id, SETTING_ACTIVE) or self.base_session_id

    def _effective_model(self) -> str | None:
        """An explicit constructor argument wins; otherwise a /model override
        set for this session; otherwise the configured default."""
        if self.model:
            return self.model
        getter = getattr(self.memory, "get_setting", None)
        return getter(self.active_session, SETTING_MODEL) if getter else None

    def _delegate_tool(self) -> dict | None:
        """Exposed only when an orchestrator is available and we are not
        already too deep. Without the depth check an agent could delegate to
        itself forever, spending real money doing it."""
        if self.orchestrator is None or self.depth >= MAX_DELEGATION_DEPTH:
            return None
        names = list((self.agents_config.get("agents") or {}).keys())
        return {
            "type": "function",
            "function": {
                "name": "delegate",
                "description": (
                    "Hand a self-contained sub-task to another configured agent and get its answer back. "
                    "Use when a step suits a different agent's model — a cheap local one for lookups, a "
                    "stronger one for hard reasoning. Available agents: " + (", ".join(names) or "none")
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "enum": names or ["none"]},
                        "task": {"type": "string", "description": "A self-contained instruction"},
                    },
                    "required": ["agent", "task"],
                },
            },
        }

    def _effective_provider(self) -> str:
        """A /model pick can select a remote model; without honouring the
        provider it stored, the request would go to the local server and fail
        in a way that looks like the model is broken."""
        getter = getattr(self.memory, "get_setting", None)
        if getter is None or self.model:
            return self.provider
        return getter(self.active_session, SETTING_PROVIDER) or self.provider

    def _all_tools(self) -> list[dict]:
        tools = self.skills.as_openai_tools()
        if self.mcp is not None:
            tools += self.mcp.as_openai_tools()
        delegate = self._delegate_tool()
        if delegate is not None:
            tools.append(delegate)
        return tools

    def _run_delegate(self, arguments: dict) -> str:
        agent = str(arguments.get("agent") or "").strip()
        task = str(arguments.get("task") or "").strip()
        if not agent or not task:
            return "error: delegate needs both 'agent' and 'task'"
        if agent not in (self.agents_config.get("agents") or {}):
            known = ", ".join((self.agents_config.get("agents") or {}).keys()) or "none"
            return f"error: no agent named '{agent}'. Configured agents: {known}"
        if agent == self.agent_name:
            return "error: an agent cannot delegate to itself"

        try:
            result = self.orchestrator.dispatch(
                agent,
                task,
                session_id=f"{self.active_session}::{agent}",
                depth=self.depth + 1,
            )
        except Exception as exc:
            return f"error delegating to '{agent}': {exc}"
        if result.error:
            return f"error from '{agent}': {result.error}"
        return f"[{agent} via {result.provider}/{result.model}]\n{result.result.output}"

    def _execute_tool(self, name: str, arguments: dict) -> str:
        if name == "delegate":
            return self._run_delegate(arguments)
        if self.mcp is not None and self.mcp.handles(name):
            return self.mcp.call(name, arguments)
        return self.skills.execute(name, arguments)

    def _call_model(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        if self.chain:
            return self.router.chat_with_fallback(self.chain, messages, tools=tools or None)
        return self.router.chat(
            self._effective_provider(), self._effective_model(), messages, tools=tools or None
        )

    def _handle_command(self, task: str) -> AgentResult:
        context = CommandContext(
            session_id=self.active_session,
            base_session_id=self.base_session_id,
            memory=self.memory,
            skills=self.skills,
            curated=self.curated,
            router=self.router,
            agents_config=self.agents_config,
            providers_config=self.providers_config,
            mcp=self.mcp,
            config=self.config_store,
        )
        output = dispatch(task, context)
        # Commands are operator actions, not conversation. Keeping them out of
        # history stops them becoming context the model tries to imitate.
        return AgentResult(output=output, metadata={"command": True})

    def _build_messages(self) -> list[dict]:
        messages: list[dict] = []
        if self.curated is not None:
            preamble = self.curated.as_system_prompt()
            if preamble:
                messages.append({"role": "system", "content": preamble})
        messages.extend(self.memory.get_history(self.active_session))
        return messages

    def _trace(self, task_id: str, kind: str, ok: bool, **fields) -> None:
        self.memory.append_trace(
            task_id=task_id,
            session_id=self.active_session,
            agent=self.agent_name,
            kind=kind,
            ok=ok,
            **fields,
        )

    def run(self, task: str, context: dict | None = None) -> AgentResult:
        if is_command(task):
            return self._handle_command(task)

        task_id = uuid4().hex
        self.last_task_id = task_id

        self.memory.append_message(self.active_session, "user", task)
        messages = self._build_messages()
        tools = self._all_tools()

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
                    output = self._execute_tool(function["name"], arguments)
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
            self.memory.append_message(self.active_session, "assistant", content)
            return AgentResult(
                output=content,
                metadata={"provider": result.provider, "model": result.model, "task_id": task_id},
            )

        fallback = "Reached the tool-call limit for this turn without a final answer — try rephrasing."
        self.memory.append_message(self.active_session, "assistant", fallback)
        return AgentResult(output=fallback, metadata={"truncated": True, "task_id": task_id})
