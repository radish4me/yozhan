"""Slash commands.

Handled in the runtime rather than in each front end, so the CLI, a Telegram
chat and the dashboard all get identical behaviour from one implementation —
the same reason every surface shares one agent loop.

Commands run *before* the model call and return directly, so `/help` costs
nothing and `/model` doesn't burn a turn.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Callable

SETTING_MODEL = "model"
SETTING_PROVIDER = "provider"


@dataclass
class CommandContext:
    """Everything a command might need, passed in so this module stays
    testable without standing up the whole runtime."""

    session_id: str
    memory: object            # SessionStore
    skills: object            # SkillManager
    curated: object | None    # CuratedMemory, when one is configured
    router: object            # ProviderRouter
    agents_config: dict
    providers_config: dict
    mcp: object | None = None  # MCPManager


@dataclass
class Command:
    name: str
    summary: str
    usage: str
    run: Callable[[CommandContext, list[str]], str]


_COMMAND_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def is_command(text: str) -> bool:
    """True only when the first token looks like a bare command name.

    Requiring that shape keeps ordinary messages out: `/etc/hosts is a file`
    and `what is 1/2` both mention slashes but neither should be swallowed as
    a command and hidden from the model.
    """
    stripped = (text or "").strip()
    if len(stripped) < 2 or not stripped.startswith("/"):
        return False
    first = stripped[1:].split()[0] if stripped[1:].split() else ""
    return bool(_COMMAND_NAME.match(first))


def parse(text: str) -> tuple[str, list[str]]:
    stripped = text.strip()[1:]
    try:
        parts = shlex.split(stripped)
    except ValueError:
        parts = stripped.split()
    if not parts:
        return "", []
    return parts[0].lower(), parts[1:]


# --- individual commands ----------------------------------------------------


def _local_model_ids(providers_config: dict) -> list[str]:
    local = (providers_config.get("providers") or {}).get("local") or {}
    return [m["id"] if isinstance(m, dict) else m for m in (local.get("models") or [])]


def _cmd_help(ctx: CommandContext, args: list[str]) -> str:
    lines = ["Available commands:"]
    for command in COMMANDS.values():
        lines.append(f"  {command.usage:<28} {command.summary}")
    lines.append("")
    lines.append("Anything not starting with / is sent to the assistant as normal.")
    return "\n".join(lines)


def _cmd_new(ctx: CommandContext, args: list[str]) -> str:
    removed = ctx.memory.clear_session(ctx.session_id)
    return f"Started a new conversation. Cleared {removed} message(s) from '{ctx.session_id}'."


def _cmd_model(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        current = ctx.memory.get_setting(ctx.session_id, SETTING_MODEL)
        default = ctx.router.default_local_model()
        return f"Model for this session: {current or f'{default} (default)'}\nUse /model <id> to change it, /models to list."

    choice = args[0]
    if choice in ("default", "reset"):
        ctx.memory.set_setting(ctx.session_id, SETTING_MODEL, None)
        return f"Model reset to the default ({ctx.router.default_local_model()})."

    known = _local_model_ids(ctx.providers_config)
    if choice not in known:
        # Don't hard-fail: providers.yaml may list remote models this doesn't
        # enumerate. Warn and accept.
        ctx.memory.set_setting(ctx.session_id, SETTING_MODEL, choice)
        return (
            f"Model for this session set to '{choice}'.\n"
            f"Note: that isn't one of the configured local models ({', '.join(known) or 'none'}), "
            "so it will fail unless a provider serves it."
        )
    ctx.memory.set_setting(ctx.session_id, SETTING_MODEL, choice)
    return f"Model for this session set to '{choice}'."


def _cmd_models(ctx: CommandContext, args: list[str]) -> str:
    lines = ["Configured models:"]
    for name, spec in (ctx.providers_config.get("providers") or {}).items():
        models = [m["id"] if isinstance(m, dict) else m for m in (spec.get("models") or [])]
        if models:
            lines.append(f"  {name}: {', '.join(models)}")
    return "\n".join(lines)


def _cmd_session(ctx: CommandContext, args: list[str]) -> str:
    history = ctx.memory.get_history(ctx.session_id)
    model = ctx.memory.get_setting(ctx.session_id, SETTING_MODEL)
    return (
        f"Session: {ctx.session_id}\n"
        f"Messages: {len(history)}\n"
        f"Model override: {model or '(none — using the default)'}"
    )


def _cmd_agents(ctx: CommandContext, args: list[str]) -> str:
    from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent

    lines = ["Agents:"]
    for name in (ctx.agents_config.get("agents") or {}):
        try:
            resolved = resolve_agent(name, ctx.agents_config, ctx.providers_config)
            lines.append(f"  {name:<16} {resolved.mode:<11} -> {resolved.provider}/{resolved.model}")
        except AgentConfigError as exc:
            lines.append(f"  {name:<16} ERROR: {exc}")
    return "\n".join(lines)


def _cmd_skills(ctx: CommandContext, args: list[str]) -> str:
    skills = ctx.skills.discovered()
    if not skills:
        return "No skills loaded."
    lines = ["Skills:"]
    for skill in skills:
        marker = f" (tool: {skill.tool_name})" if skill.tool_name else ""
        lines.append(f"  {skill.name}{marker} — {skill.description}")
    return "\n".join(lines)


def _cmd_tools(ctx: CommandContext, args: list[str]) -> str:
    names = [t["function"]["name"] for t in ctx.skills.as_openai_tools()]
    if ctx.mcp is not None:
        names += [t["function"]["name"] for t in ctx.mcp.as_openai_tools()]
    if not names:
        return "No callable tools available."
    return "Callable tools:\n" + "\n".join(f"  {n}" for n in sorted(names))


def _cmd_mcp(ctx: CommandContext, args: list[str]) -> str:
    if ctx.mcp is None or not ctx.mcp.configs:
        return (
            "MCP is not configured. Add servers under `mcp:` in config/agents.yaml "
            "and set `mcp.enabled: true`."
        )
    lines = ["MCP servers:"]
    for server in ctx.mcp.describe():
        if server["connected"]:
            tools = ", ".join(server["tools"]) or "(no tools)"
            lines.append(f"  {server['name']}: connected — {tools}")
        else:
            lines.append(f"  {server['name']}: NOT CONNECTED — {server['error']}")
    return "\n".join(lines)


def _cmd_memory(ctx: CommandContext, args: list[str]) -> str:
    if ctx.curated is None:
        return "Curated memory isn't available in this context."
    memory = ctx.curated.read("memory").strip()
    user = ctx.curated.read("user").strip()
    parts = []
    if user:
        parts.append(f"USER.md:\n{user}")
    if memory:
        parts.append(f"MEMORY.md:\n{memory}")
    return "\n\n".join(parts) if parts else "Curated memory is empty. Use /remember <note> to add something."


def _cmd_remember(ctx: CommandContext, args: list[str]) -> str:
    if ctx.curated is None:
        return "Curated memory isn't available in this context."
    if not args:
        return "Usage: /remember <note>"
    note = " ".join(args)
    from yozhan_runtime.memory.curated import MemoryCapExceeded

    try:
        ctx.curated.add(note)
    except MemoryCapExceeded as exc:
        return f"error: {exc}"
    return f"Remembered: {note}"


def _cmd_forget(ctx: CommandContext, args: list[str]) -> str:
    if ctx.curated is None:
        return "Curated memory isn't available in this context."
    if not args:
        return "Usage: /forget <text to match>"
    ctx.curated.remove(" ".join(args))
    return f"Removed notes matching '{' '.join(args)}'."


def _cmd_search(ctx: CommandContext, args: list[str]) -> str:
    if not args:
        return "Usage: /search <query>"
    results = ctx.memory.search(" ".join(args), limit=10)
    if not results:
        return "No matches in past conversations."
    lines = [f"{len(results)} match(es):"]
    for row in results:
        snippet = row["content"].replace("\n", " ")[:120]
        lines.append(f"  [{row['session_id']}] {row['role']}: {snippet}")
    return "\n".join(lines)


def _cmd_costs(ctx: CommandContext, args: list[str]) -> str:
    group = args[0] if args else "agent"
    group = "name" if group == "model" else group
    try:
        rows = ctx.memory.cost_summary(group)
    except ValueError as exc:
        return f"error: {exc}"
    if not rows:
        return "No traces recorded yet."
    lines = [f"{'key':<20}{'calls':>7}{'fails':>7}{'avg ms':>9}{'USD':>10}"]
    for row in rows:
        lines.append(
            f"{row['key']:<20}{row['calls']:>7}{row['failures']:>7}"
            f"{(row['avg_latency_ms'] or 0):>9.0f}{row['total_cost_usd']:>10.4f}"
        )
    return "\n".join(lines)


def _cmd_skill(ctx: CommandContext, args: list[str]) -> str:
    """`/skill new <name>` returns a template to fill in.

    Deliberately does not write the file: skills are executable instructions,
    and creating one from a chat message with no review is how an assistant
    quietly acquires behaviour nobody chose. Save it from the dashboard's
    Skills tab, which shows the whole document first.
    """
    if not args or args[0] != "new" or len(args) < 2:
        return "Usage: /skill new <skill-name>"
    name = args[1]
    return (
        f"Here is a starting point for '{name}'. Review it, then save it from the "
        f"dashboard's Skills tab:\n\n"
        f"---\nname: {name}\nversion: 0.1.0\ndescription: What this skill does.\n"
        f"capabilities: []\ntags: []\ndepends_on: []\n---\n\n"
        f"# {name}\n\n1. First step.\n2. Second step.\n"
    )


COMMANDS: dict[str, Command] = {
    c.name: c
    for c in [
        Command("help", "Show this list.", "/help", _cmd_help),
        Command("new", "Clear this conversation and start fresh.", "/new", _cmd_new),
        Command("model", "Show or set the model for this session.", "/model [id|default]", _cmd_model),
        Command("models", "List every configured model.", "/models", _cmd_models),
        Command("session", "Show this session's id and settings.", "/session", _cmd_session),
        Command("agents", "List agents and their resolved models.", "/agents", _cmd_agents),
        Command("skills", "List loaded skills.", "/skills", _cmd_skills),
        Command("skill", "Scaffold a new skill.", "/skill new <name>", _cmd_skill),
        Command("tools", "List callable tools, including MCP.", "/tools", _cmd_tools),
        Command("mcp", "Show MCP servers and their status.", "/mcp", _cmd_mcp),
        Command("memory", "Show curated cross-session memory.", "/memory", _cmd_memory),
        Command("remember", "Add a note to durable memory.", "/remember <note>", _cmd_remember),
        Command("forget", "Remove matching notes from memory.", "/forget <text>", _cmd_forget),
        Command("search", "Search past conversations.", "/search <query>", _cmd_search),
        Command("costs", "Cost and latency summary.", "/costs [agent|model|provider]", _cmd_costs),
    ]
}

# Aliases for the things people reach for by another name.
ALIASES = {"clear": "new", "reset": "new", "h": "help", "?": "help", "history": "search"}


def dispatch(text: str, ctx: CommandContext) -> str:
    """Runs a slash command. Assumes is_command(text) already returned True."""
    name, args = parse(text)
    name = ALIASES.get(name, name)
    command = COMMANDS.get(name)
    if command is None:
        close = [c for c in COMMANDS if c.startswith(name[:3])] if name else []
        hint = f" Did you mean /{close[0]}?" if close else " Try /help."
        return f"Unknown command '/{name}'.{hint}"
    try:
        return command.run(ctx, args)
    except Exception as exc:  # a bad command must not kill the chat session
        return f"error running /{name}: {exc}"
