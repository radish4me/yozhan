"""FastAPI surface for the agent runtime. Serves the same ChatAgent/Orchestrator
used by the CLI so the Gateway (Phase 5) talks to identical behavior.
See ARCHITECTURE.md sections 3.1-3.4.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.agents.orchestrator import Orchestrator
from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent
from yozhan_runtime.config import load_agents, skills_dirs
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ProviderError, ProviderRouter
from yozhan_runtime.skills.manager import SkillManager

app = FastAPI(title="yozhan-runtime")

_router = ProviderRouter()
_skills = SkillManager(skills_dirs())
_skills.discover()
_memory = SessionStore()
_orchestrator = Orchestrator(router=_router, skills=_skills, memory=_memory)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    model: str | None = None


class OrchestrateRequest(BaseModel):
    assignments: list[tuple[str, str]]  # [(agent_name, task), ...]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    agent = ChatAgent(
        router=_router,
        skills=_skills,
        memory=_memory,
        session_id=request.session_id,
        model=request.model,
    )
    try:
        result = agent.run(request.message)
    except ProviderError as exc:
        return {"error": str(exc)}
    return {"content": result.output, "metadata": result.metadata}


@app.get("/agents")
def list_agents():
    """Each configured agent with its resolved (provider, model) — ARCHITECTURE.md section 4.2."""
    agents_config = load_agents()
    out = []
    for name in agents_config.get("agents", {}):
        try:
            resolved = resolve_agent(name)
            out.append(
                {
                    "name": resolved.name,
                    "mode": resolved.mode,
                    "subagent_of": resolved.subagent_of,
                    "provider": resolved.provider,
                    "model": resolved.model,
                }
            )
        except AgentConfigError as exc:
            out.append({"name": name, "error": str(exc)})
    return out


@app.post("/orchestrate")
def orchestrate(request: OrchestrateRequest):
    results = _orchestrator.dispatch_many(request.assignments)
    return [
        {
            "agent": r.agent,
            "provider": r.provider,
            "model": r.model,
            "output": r.result.output if r.result else None,
            "error": r.error,
        }
        for r in results
    ]
