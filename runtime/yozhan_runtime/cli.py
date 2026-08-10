"""yozhan CLI. Phase 2: `yozhan chat` is a full ChatAgent session (tool-calling
+ persisted history via SessionStore); `yozhan serve` runs the HTTP API the
Gateway will call starting Phase 5.
"""

from __future__ import annotations

import click

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.config import skills_dirs
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ProviderError, ProviderRouter
from yozhan_runtime.skills.manager import SkillManager


@click.group()
def main():
    """yozhan — self-hosted AI assistant."""


@main.command()
@click.option("--model", default=None, help="Override the local model id (default: providers.yaml's default_model).")
@click.option("--session", default="default", help="Session id — history persists across restarts under this id.")
def chat(model: str | None, session: str):
    """Start an interactive chat REPL against the local llama.cpp model."""
    router = ProviderRouter()
    skills = SkillManager(skills_dirs())
    loaded = skills.discover()
    memory = SessionStore()
    agent = ChatAgent(router=router, skills=skills, memory=memory, session_id=session, model=model)

    tool_names = [s.tool_name for s in loaded if s.tool_name]
    click.echo(
        f"yozhan chat — model: {model or router.default_local_model()} | session: {session} | "
        f"tools: {', '.join(tool_names) or 'none'} (Ctrl-D to exit)"
    )
    while True:
        try:
            user_input = click.prompt("you", prompt_suffix="> ")
        except (EOFError, click.exceptions.Abort):
            click.echo("\nbye")
            break
        try:
            result = agent.run(user_input)
        except ProviderError as exc:
            click.echo(f"error: {exc}", err=True)
            continue
        click.echo(f"yozhan> {result.output}")
    memory.close()


@main.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8787, type=int)
def serve(host: str, port: int):
    """Run the agent runtime's HTTP API (used by the Gateway)."""
    import uvicorn

    from yozhan_runtime.server import app

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
