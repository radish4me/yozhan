"""FastAPI surface for the agent runtime. Serves the same ChatAgent/Orchestrator
used by the CLI so the Gateway (Phase 5) talks to identical behavior.
See ARCHITECTURE.md sections 3.1-3.4.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.agents.orchestrator import Orchestrator
from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent
from yozhan_runtime.config import load_agents, load_providers, skills_dirs, user_skills_dir
from yozhan_runtime.learning.reviewer import apply_proposal, reviewer_from_config
from yozhan_runtime.memory.curated import CuratedMemory
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ProviderError, ProviderRouter
from yozhan_runtime.a2a.card import build_agent_card
from yozhan_runtime.a2a.server import build_router as build_a2a_router
from yozhan_runtime.sandbox.policy import sandbox_from_config
from yozhan_runtime.skills.manager import SkillManager

app = FastAPI(title="yozhan-runtime")

_agents_config = load_agents()
_providers_config = load_providers()
_router = ProviderRouter()
_skills = SkillManager(skills_dirs(), sandbox_policy=sandbox_from_config(_agents_config))
_skills.discover()
_memory = SessionStore()
_curated = CuratedMemory()
_orchestrator = Orchestrator(
    router=_router,
    skills=_skills,
    memory=_memory,
    agents_config=_agents_config,
    providers_config=_providers_config,
    curated=_curated,
    reviewer=reviewer_from_config(_memory, _router, _agents_config, _providers_config),
)


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
        curated=_curated,
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


@app.get("/skills")
def list_skills():
    """Loaded skills — powers the dashboard's skill inspector."""
    return [
        {
            "name": s.name,
            "version": s.version,
            "description": s.description,
            "tags": s.tags,
            "tool": s.tool_name,
            "elevated": s.elevated,
        }
        for s in _skills.discovered()
    ]


@app.get("/providers")
def list_providers():
    """Configured providers and their models. Never returns key values —
    only whether a key is present, so the dashboard can show health without
    the API ever handing out a credential."""
    providers = (load_providers().get("providers") or {}).items()
    out = []
    for name, cfg in providers:
        models = [m["id"] if isinstance(m, dict) else m for m in (cfg.get("models") or [])]
        configured_keys = sum(
            1 for entry in (cfg.get("api_keys") or []) if os.environ.get(entry.get("env", ""))
        )
        out.append(
            {
                "name": name,
                "type": cfg.get("type", name),
                "models": models,
                "keys_configured": configured_keys,
                "keys_declared": len(cfg.get("api_keys") or []),
            }
        )
    return out


@app.get("/costs")
def costs(by: str = "agent"):
    """Cost/latency rollup from the trace log (ROADMAP.md Phase 7)."""
    try:
        return _memory.cost_summary(by)
    except ValueError as exc:
        return {"error": str(exc)}


@app.get("/proposals")
def proposals(status: str = "pending"):
    """Staged skill proposals from the learning loop."""
    return _memory.list_proposals(status)


@app.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: int):
    try:
        path = apply_proposal(_memory, proposal_id, user_skills_dir())
    except ValueError as exc:
        return {"error": str(exc)}
    _skills.discover()  # make the newly approved skill callable immediately
    return {"approved": proposal_id, "path": str(path)}


@app.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int):
    if _memory.get_proposal(proposal_id) is None:
        return {"error": f"no proposal #{proposal_id}"}
    _memory.set_proposal_status(proposal_id, "rejected")
    return {"rejected": proposal_id}


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


# --- A2A (ROADMAP.md Phase 8) -------------------------------------------
# Mounted only when explicitly enabled: turning this on exposes the agent to
# other agents, so it is never on by accident.
_a2a_config = _agents_config.get("a2a") or {}
if _a2a_config.get("enabled", False):

    def _run_a2a_task(text: str, session_id: str) -> str:
        agent = ChatAgent(
            router=_router,
            skills=_skills,
            memory=_memory,
            session_id=session_id,
            curated=_curated,
            agent_name="a2a",
        )
        try:
            return agent.run(text).output
        except ProviderError as exc:
            return f"error: {exc}"

    def _agent_card() -> dict:
        return build_agent_card(
            name=_a2a_config.get("agent_name", "yozhan"),
            description=_a2a_config.get("agent_description", "A self-hosted personal AI assistant."),
            url=_a2a_config.get("public_url", "http://localhost:8787/a2a"),
            skills=_skills.discovered(),
            requires_auth=_a2a_config.get("require_token", True),
        )

    app.include_router(build_a2a_router(_a2a_config, _agent_card, _run_a2a_task))
