"""Minimal FastAPI surface for the agent runtime. Phase 1: health + a single
/chat passthrough to the local model, so the Gateway (Phase 5) has something
real to call from day one. Agent loop, skills, and memory wire in from
Phase 2 onward per ROADMAP.md.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from yozhan_runtime.providers.router import ProviderError, ProviderRouter

app = FastAPI(title="yozhan-runtime")
router = ProviderRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    messages = [m.model_dump() for m in request.messages]
    try:
        result = router.chat_local(messages, model=request.model)
    except ProviderError as exc:
        return {"error": str(exc)}
    return {"provider": result.provider, "model": result.model, "content": result.content}
