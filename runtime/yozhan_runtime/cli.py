"""yozhan CLI. Phase 1 scope: `yozhan chat` (REPL against the local model) and
`yozhan serve` (health/chat HTTP API for the Gateway to call).
"""

from __future__ import annotations

import click

from yozhan_runtime.providers.router import ProviderError, ProviderRouter


@click.group()
def main():
    """yozhan — self-hosted AI assistant."""


@main.command()
@click.option("--model", default=None, help="Override the local model id (default: providers.yaml's default_model).")
def chat(model: str | None):
    """Start an interactive chat REPL against the local llama.cpp model."""
    router = ProviderRouter()
    history: list[dict] = []
    click.echo(f"yozhan chat — model: {model or router.default_local_model()} (Ctrl-D to exit)")
    while True:
        try:
            user_input = click.prompt("you", prompt_suffix="> ")
        except (EOFError, click.exceptions.Abort):
            click.echo("\nbye")
            break
        history.append({"role": "user", "content": user_input})
        try:
            result = router.chat_local(history, model=model)
        except ProviderError as exc:
            click.echo(f"error: {exc}", err=True)
            continue
        history.append({"role": "assistant", "content": result.content})
        click.echo(f"yozhan> {result.content}")


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
