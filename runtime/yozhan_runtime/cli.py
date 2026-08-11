"""yozhan CLI.

  chat        single ChatAgent session (Phase 2)
  agents      each configured agent's resolved model assignment (Phase 3)
  orchestrate dispatch tasks across several agents (Phase 3)
  memory      inspect/edit curated cross-session memory (Phase 6)
  learn       review traces and approve staged skill proposals (Phase 6)
  costs       per-agent cost/latency from the trace log (Phase 7)
  scheduler   run scheduled/continuous agents (Phase 7)
  serve       the HTTP API the Gateway calls (Phase 5)
"""

from __future__ import annotations

import click

from yozhan_runtime.agents.chat_agent import ChatAgent
from yozhan_runtime.agents.orchestrator import Orchestrator
from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent
from yozhan_runtime.config import load_agents, load_providers, skills_dirs, user_skills_dir
from yozhan_runtime.learning.reviewer import apply_proposal, reviewer_from_config
from yozhan_runtime.memory.curated import CuratedMemory, MemoryCapExceeded
from yozhan_runtime.memory.store import SessionStore
from yozhan_runtime.providers.router import ProviderError, ProviderRouter
from yozhan_runtime.sandbox.policy import sandbox_from_config
from yozhan_runtime.scheduling.scheduler import Scheduler
from yozhan_runtime.skills.manager import SkillManager


def _build_runtime(agent_name: str | None = None):
    """The standard set of runtime objects every command needs."""
    router = ProviderRouter()
    policy = sandbox_from_config(load_agents(), agent_name)
    skills = SkillManager(skills_dirs(), sandbox_policy=policy)
    skills.discover()
    memory = SessionStore()
    curated = CuratedMemory()
    return router, skills, memory, curated


@click.group()
def main():
    """yozhan — self-hosted AI assistant."""


@main.command()
@click.option("--model", default=None, help="Override the local model id (default: providers.yaml's default_model).")
@click.option("--session", default="default", help="Session id — history persists across restarts under this id.")
def chat(model: str | None, session: str):
    """Start an interactive chat REPL against the local llama.cpp model."""
    router, skills, memory, curated = _build_runtime()
    reviewer = reviewer_from_config(memory, router, load_agents(), load_providers())
    agent = ChatAgent(
        router=router,
        skills=skills,
        memory=memory,
        session_id=session,
        model=model,
        curated=curated,
    )

    tool_names = [s.tool_name for s in skills.discovered() if s.tool_name]
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

        if reviewer is not None and agent.last_task_id:
            try:
                proposal_id = reviewer.review_task(
                    agent.last_task_id, session, [s.name for s in skills.discovered()]
                )
                if proposal_id:
                    click.echo(f"  (learned something — staged skill proposal #{proposal_id}, "
                               f"review with `yozhan learn pending`)")
            except Exception as exc:  # never let the background reviewer break the chat
                click.echo(f"  (learning review skipped: {exc})", err=True)
    memory.close()


@main.command(name="agents")
def list_agents():
    """List every agent in config/agents.yaml with its resolved provider/model."""
    agents_config = load_agents()
    for name in agents_config.get("agents", {}):
        try:
            resolved = resolve_agent(name, agents_config)
        except AgentConfigError as exc:
            click.echo(f"{name:<16} ERROR: {exc}", err=True)
            continue
        parent = resolved.subagent_of or "-"
        click.echo(
            f"{name:<16} mode={resolved.mode:<10} subagent_of={parent:<14} "
            f"-> {resolved.provider}/{resolved.model}"
        )


@main.command()
@click.option(
    "--agent",
    "assignments",
    type=(str, str),
    multiple=True,
    required=True,
    help='Agent name + task, repeatable: --agent researcher "task" --agent coder "task"',
)
def orchestrate(assignments: tuple[tuple[str, str], ...]):
    """Dispatch tasks to named agents, each resolving its own model assignment."""
    router, skills, memory, curated = _build_runtime()
    agents_config, providers_config = load_agents(), load_providers()
    orchestrator = Orchestrator(
        router=router,
        skills=skills,
        memory=memory,
        agents_config=agents_config,
        providers_config=providers_config,
        curated=curated,
        reviewer=reviewer_from_config(memory, router, agents_config, providers_config),
    )

    for dispatched in orchestrator.dispatch_many(list(assignments)):
        click.echo(f"[{dispatched.agent}] {dispatched.provider}/{dispatched.model}")
        if dispatched.error:
            click.echo(f"  error: {dispatched.error}", err=True)
        else:
            click.echo(f"  -> {dispatched.result.output}")
    memory.close()


@main.group()
def memory():
    """Inspect and edit curated cross-session memory (MEMORY.md / USER.md)."""


@memory.command(name="show")
@click.option("--kind", type=click.Choice(["memory", "user"]), default="memory")
def memory_show(kind: str):
    """Print the current contents of a curated memory file."""
    contents = CuratedMemory().read(kind)
    click.echo(contents.rstrip() if contents.strip() else f"({kind} memory is empty)")


@memory.command(name="add")
@click.argument("note")
@click.option("--kind", type=click.Choice(["memory", "user"]), default="memory")
def memory_add(note: str, kind: str):
    """Add a note to curated memory."""
    try:
        CuratedMemory().add(note, kind)
    except MemoryCapExceeded as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"recorded in {'MEMORY.md' if kind == 'memory' else 'USER.md'}")


@memory.command(name="remove")
@click.argument("substring")
@click.option("--kind", type=click.Choice(["memory", "user"]), default="memory")
def memory_remove(substring: str, kind: str):
    """Remove every note containing SUBSTRING."""
    CuratedMemory().remove(substring, kind)
    click.echo(f"removed notes matching {substring!r} from {'MEMORY.md' if kind == 'memory' else 'USER.md'}")


@main.group()
def learn():
    """Review traces and manage staged skill proposals (learning loop)."""


@learn.command(name="review")
@click.option("--session", default="default", help="Session whose recent tasks should be reviewed.")
@click.option("--limit", default=5, help="How many recent tasks to review.")
def learn_review(session: str, limit: int):
    """Run the learning reviewer over recent tasks and stage any proposals."""
    router, skills, memory, _ = _build_runtime()
    reviewer = reviewer_from_config(memory, router, load_agents(), load_providers())
    if reviewer is None:
        raise click.ClickException("learning is disabled — set learning.enabled: true in config/agents.yaml")

    existing = [s.name for s in skills.discovered()]
    staged = 0
    for task_id in memory.list_task_ids(limit=limit):
        proposal_id = reviewer.review_task(task_id, session, existing_skills=existing)
        if proposal_id:
            staged += 1
            click.echo(f"staged proposal #{proposal_id} from task {task_id[:8]}")
    click.echo(f"{staged} proposal(s) staged" if staged else "nothing worth learning from recent tasks")
    memory.close()


@learn.command(name="pending")
def learn_pending():
    """List staged skill proposals awaiting approval."""
    store = SessionStore()
    proposals = store.list_proposals("pending")
    if not proposals:
        click.echo("no pending proposals")
    for proposal in proposals:
        click.echo(f"#{proposal['id']} {proposal['action']} {proposal['skill_name']} — {proposal['rationale']}")
    store.close()


@learn.command(name="show")
@click.argument("proposal_id", type=int)
def learn_show(proposal_id: int):
    """Print a staged proposal's full SKILL.md."""
    store = SessionStore()
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise click.ClickException(f"no proposal #{proposal_id}")
    click.echo(proposal["content"])
    store.close()


@learn.command(name="approve")
@click.argument("proposal_id", type=int)
def learn_approve(proposal_id: int):
    """Approve a staged proposal, writing it into the user skills directory."""
    store = SessionStore()
    try:
        path = apply_proposal(store, proposal_id, user_skills_dir())
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        store.close()
    click.echo(f"wrote {path}")


@learn.command(name="reject")
@click.argument("proposal_id", type=int)
def learn_reject(proposal_id: int):
    """Reject a staged proposal."""
    store = SessionStore()
    if store.get_proposal(proposal_id) is None:
        store.close()
        raise click.ClickException(f"no proposal #{proposal_id}")
    store.set_proposal_status(proposal_id, "rejected")
    store.close()
    click.echo(f"rejected proposal #{proposal_id}")


@main.command()
@click.option(
    "--by",
    type=click.Choice(["agent", "name", "provider"]),
    default="agent",
    help="Group by agent, model name, or provider.",
)
def costs(by: str):
    """Per-agent cost and latency from the trace log (Phase 6 data)."""
    store = SessionStore()
    rows = store.cost_summary(by)
    if not rows:
        click.echo("no traces recorded yet")
        store.close()
        return

    click.echo(f"{by:<16} {'calls':>6} {'fails':>6} {'avg ms':>9} {'tokens':>9} {'USD':>10}")
    for row in rows:
        click.echo(
            f"{row['key']:<16} {row['calls']:>6} {row['failures']:>6} "
            f"{(row['avg_latency_ms'] or 0):>9.0f} {row['total_tokens']:>9} "
            f"{row['total_cost_usd']:>10.4f}"
        )
    store.close()


@main.command()
def scheduler():
    """Run scheduled and continuous agents (ticks once a minute)."""
    router, skills, memory, curated = _build_runtime()
    agents_config, providers_config = load_agents(), load_providers()
    orchestrator = Orchestrator(
        router=router,
        skills=skills,
        memory=memory,
        agents_config=agents_config,
        providers_config=providers_config,
        curated=curated,
        reviewer=reviewer_from_config(memory, router, agents_config, providers_config),
    )
    loop = Scheduler(orchestrator, agents_config)
    if not loop.agents:
        raise click.ClickException(
            "no scheduled or continuous agents configured — add one with mode: scheduled in config/agents.yaml"
        )
    click.echo(f"scheduler running: {', '.join(a.name for a in loop.agents)} (Ctrl-C to stop)")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        click.echo("\nstopped")
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
