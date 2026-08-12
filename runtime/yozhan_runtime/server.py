"""FastAPI surface for the agent runtime. Serves the same ChatAgent/Orchestrator
the CLI uses, plus the config, secrets, skills and memory endpoints the
dashboard edits through.

Config is read via a ConfigStore that reparses when the file changes, so a
save from the dashboard takes effect on the next task instead of at the next
restart. Objects built *from* config (skills, sandbox policy, orchestrator)
are rebuilt on demand for the same reason — see `runtime()`.

See ARCHITECTURE.md sections 3.1-3.4 and ROADMAP.md Phases 5, 9-12.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from yozhan_runtime.a2a.card import build_agent_card
from yozhan_runtime.a2a.server import build_router as build_a2a_router
from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.agents.orchestrator import Orchestrator
from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent
from yozhan_runtime.config import skills_dirs, user_skills_dir
from yozhan_runtime.config_store import CONFIG_FILES, ConfigStore, ConfigValidationError
from yozhan_runtime.learning.reviewer import apply_proposal, reviewer_from_config
from yozhan_runtime.memory.curated import CuratedMemory, MemoryCapExceeded
from yozhan_runtime.mcp import MCPManager, servers_from_config
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ProviderError, ProviderRouter
from yozhan_runtime.sandbox.policy import sandbox_from_config
from yozhan_runtime.secrets import SecretError, SecretStore, validate_name
from yozhan_runtime.skills.manager import SkillManager

app = FastAPI(title="yozhan-runtime")

config = ConfigStore()
secrets = SecretStore()
secrets.apply_to_environment()

_memory = SessionStore()
_curated = CuratedMemory()

# Rebuilt whenever config changes on disk; see runtime().
_cached: dict = {"signature": None}


def runtime():
    """The config-derived objects, rebuilt when either config file changes.

    Keyed on the parsed config so an edit through the dashboard — or a hand
    edit on the volume — is picked up without a restart.
    """
    agents_config = config.agents()
    providers_config = config.providers()
    signature = (id(agents_config), id(providers_config))

    if _cached.get("signature") != signature:
        router = ProviderRouter(config=providers_config)
        skills = SkillManager(skills_dirs(), sandbox_policy=sandbox_from_config(agents_config))
        skills.discover()

        # MCP servers are subprocesses; stop the old set before starting a new
        # one, or a config reload leaks a process per edit.
        previous = _cached.get("mcp")
        if previous is not None:
            previous.stop()
        mcp = MCPManager(servers_from_config(agents_config))
        mcp.start()

        _cached.update(
            signature=signature,
            router=router,
            skills=skills,
            mcp=mcp,
            orchestrator=Orchestrator(
                router=router,
                skills=skills,
                memory=_memory,
                agents_config=agents_config,
                providers_config=providers_config,
                curated=_curated,
                reviewer=reviewer_from_config(_memory, router, agents_config, providers_config),
            ),
        )
    return _cached


def actor(x_yozhan_user: str | None) -> str:
    """Who made a change, for the audit log. Supplied by the gateway, which is
    the component that knows who is logged in."""
    return x_yozhan_user or "unknown"


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    model: str | None = None


class OrchestrateRequest(BaseModel):
    assignments: list[tuple[str, str]]


class ConfigWrite(BaseModel):
    content: str


class SecretWrite(BaseModel):
    name: str
    value: str


class SkillWrite(BaseModel):
    content: str


class MemoryWrite(BaseModel):
    content: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    rt = runtime()
    agent = ChatAgent(
        router=rt["router"],
        skills=rt["skills"],
        memory=_memory,
        session_id=request.session_id,
        model=request.model,
        curated=_curated,
        mcp=rt["mcp"],
        agents_config=config.agents(),
        providers_config=config.providers(),
    )
    try:
        result = agent.run(request.message)
    except ProviderError as exc:
        return {"error": str(exc)}
    return {"content": result.output, "metadata": result.metadata}


@app.post("/orchestrate")
def orchestrate(request: OrchestrateRequest):
    results = runtime()["orchestrator"].dispatch_many(request.assignments)
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


# --- inspection ------------------------------------------------------------


@app.get("/agents")
def list_agents():
    agents_config = config.agents()
    out = []
    for name in agents_config.get("agents", {}):
        try:
            resolved = resolve_agent(name, agents_config, config.providers())
            out.append(
                {
                    "name": resolved.name,
                    "mode": resolved.mode,
                    "subagent_of": resolved.subagent_of,
                    "provider": resolved.provider,
                    "model": resolved.model,
                    "sandbox": resolved.sandbox,
                }
            )
        except AgentConfigError as exc:
            out.append({"name": name, "error": str(exc)})
    return out


@app.get("/mcp")
def list_mcp():
    """MCP servers and their status — powers /mcp and the dashboard."""
    return runtime()["mcp"].describe()


@app.get("/commands")
def list_commands():
    """The slash commands available, so the dashboard can show them."""
    from yozhan_runtime.commands import COMMANDS

    return [{"name": c.name, "usage": c.usage, "summary": c.summary} for c in COMMANDS.values()]


@app.get("/skills")
def list_skills():
    return [
        {
            "name": s.name,
            "version": s.version,
            "description": s.description,
            "tags": s.tags,
            "tool": s.tool_name,
            "elevated": s.elevated,
            "editable": _is_user_skill(s.path),
        }
        for s in runtime()["skills"].discovered()
    ]


@app.get("/providers")
def list_providers():
    """Never returns key values — only whether one is present."""
    out = []
    for name, cfg in (config.providers().get("providers") or {}).items():
        models = [m["id"] if isinstance(m, dict) else m for m in (cfg.get("models") or [])]
        declared = cfg.get("api_keys") or []
        out.append(
            {
                "name": name,
                "type": cfg.get("type", name),
                "models": models,
                "keys_configured": sum(1 for e in declared if os.environ.get(e.get("env", ""))),
                "keys_declared": len(declared),
                "key_names": [e.get("env") for e in declared],
            }
        )
    return out


@app.get("/costs")
def costs(by: str = "agent"):
    try:
        return _memory.cost_summary("name" if by == "model" else by)
    except ValueError as exc:
        return {"error": str(exc)}


@app.get("/proposals")
def proposals(status: str = "pending"):
    return _memory.list_proposals(status)


@app.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: int):
    try:
        path = apply_proposal(_memory, proposal_id, user_skills_dir())
    except ValueError as exc:
        return {"error": str(exc)}
    runtime()["skills"].discover()
    return {"approved": proposal_id, "path": str(path)}


@app.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int):
    if _memory.get_proposal(proposal_id) is None:
        return {"error": f"no proposal #{proposal_id}"}
    _memory.set_proposal_status(proposal_id, "rejected")
    return {"rejected": proposal_id}


# --- config ----------------------------------------------------------------


@app.get("/config")
def config_index():
    return {"files": list(CONFIG_FILES), "backups": [b.__dict__ for b in config.list_backups()]}


@app.get("/config/audit")
def config_audit(limit: int = 50):
    return config.audit_log(limit)


@app.get("/config/{name}")
def read_config(name: str):
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config file '{name}'")
    return {"name": name, "content": config.raw(name), "parsed": config.get(name)}


@app.post("/config/{name}/validate")
def validate_config(name: str, body: ConfigWrite):
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config file '{name}'")
    try:
        config.validate_candidate(name, body.content)
    except ConfigValidationError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True}


@app.put("/config/{name}")
def write_config(name: str, body: ConfigWrite, x_yozhan_user: str | None = Header(default=None)):
    if name not in CONFIG_FILES:
        raise HTTPException(status_code=404, detail=f"unknown config file '{name}'")
    try:
        config.write(name, body.content, actor=actor(x_yozhan_user))
    except ConfigValidationError as exc:
        # 422, not 500: the request was well-formed, the content was not.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"saved": name}


@app.post("/config/restore/{backup_id}")
def restore_config(backup_id: str, x_yozhan_user: str | None = Header(default=None)):
    try:
        config.restore(backup_id, actor=actor(x_yozhan_user))
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"restored": backup_id}


@app.get("/config/backup/{backup_id}")
def read_backup(backup_id: str):
    try:
        return {"id": backup_id, "content": config.read_backup(backup_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- secrets ---------------------------------------------------------------


@app.get("/secrets")
def list_secrets():
    """Names and status only. Values are never returned."""
    return secrets.describe()


@app.put("/secrets")
def set_secret(body: SecretWrite):
    try:
        secrets.set(body.name, body.value)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _cached["signature"] = None  # rebuild the router so it picks up the new key
    return {"saved": body.name}


@app.delete("/secrets/{name}")
def delete_secret(name: str):
    try:
        validate_name(name)
        secrets.delete(name)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _cached["signature"] = None
    return {"deleted": name}


# --- skills ----------------------------------------------------------------


def _is_user_skill(path: Path) -> bool:
    """Only skills in the user directory are editable; the shipped ones live in
    the image and would be silently reverted on the next deploy."""
    try:
        return user_skills_dir().resolve() in Path(path).resolve().parents
    except OSError:
        return False


def _user_skill_path(name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid skill name")
    base = user_skills_dir().resolve()
    target = (base / name).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="invalid skill name")
    return target


@app.get("/skills/{name}")
def read_skill(name: str):
    for skill in runtime()["skills"].discovered():
        if skill.name == name:
            return {
                "name": name,
                "content": (skill.path / "SKILL.md").read_text(encoding="utf-8"),
                "editable": _is_user_skill(skill.path),
            }
    raise HTTPException(status_code=404, detail=f"no skill '{name}'")


@app.put("/skills/{name}")
def write_skill(name: str, body: SkillWrite):
    from yozhan_runtime.learning.reviewer import parse_skill_document

    parsed = parse_skill_document(body.content)
    if parsed is None:
        raise HTTPException(
            status_code=422,
            detail="Not a valid SKILL.md: needs YAML frontmatter with a lowercase-kebab-case `name` and a `description`.",
        )
    if parsed[0] != name:
        raise HTTPException(status_code=422, detail=f"frontmatter name '{parsed[0]}' does not match '{name}'")

    target = _user_skill_path(name)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(body.content.rstrip() + "\n", encoding="utf-8")
    runtime()["skills"].discover()
    return {"saved": name}


@app.delete("/skills/{name}")
def delete_skill(name: str):
    target = _user_skill_path(name)
    manifest = target / "SKILL.md"
    if not manifest.is_file():
        raise HTTPException(status_code=404, detail=f"no user skill '{name}' (built-in skills cannot be deleted)")
    manifest.unlink()
    for leftover in target.glob("*"):
        leftover.unlink()
    target.rmdir()
    runtime()["skills"].discover()
    return {"deleted": name}


# --- curated memory --------------------------------------------------------


@app.get("/memory/{kind}")
def read_memory(kind: str):
    try:
        return {"kind": kind, "content": _curated.read(kind)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/memory/{kind}")
def write_memory(kind: str, body: MemoryWrite):
    try:
        _curated.write(body.content, kind)
    except MemoryCapExceeded as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"saved": kind}


# --- A2A (optional) --------------------------------------------------------

_a2a_config = config.agents().get("a2a") or {}
if _a2a_config.get("enabled", False):

    def _run_a2a_task(text: str, session_id: str) -> str:
        rt = runtime()
        agent = ChatAgent(
            router=rt["router"],
            skills=rt["skills"],
            memory=_memory,
            session_id=session_id,
            curated=_curated,
            agent_name="a2a",
            mcp=rt["mcp"],
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
            skills=runtime()["skills"].discovered(),
            requires_auth=_a2a_config.get("require_token", True),
        )

    app.include_router(build_a2a_router(_a2a_config, _agent_card, _run_a2a_task))
