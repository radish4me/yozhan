"""FastAPI surface for the agent runtime. Serves the same ChatAgent used by
the CLI (tool-calling + persisted per-session history) so the Gateway
(Phase 5) talks to identical behavior. See ARCHITECTURE.md sections 3.1-3.4.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.config import skills_dirs
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ProviderError, ProviderRouter
from yozhan_runtime.skills.manager import SkillManager

app = FastAPI(title="yozhan-runtime")

_router = ProviderRouter()
_skills = SkillManager(skills_dirs())
_skills.discover()
_memory = SessionStore()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    model: str | None = None


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
