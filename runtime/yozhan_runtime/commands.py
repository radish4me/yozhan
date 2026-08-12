"""Slash commands.

Handled in the runtime rather than in each front end, so the CLI, a Telegram
chat and the dashboard all get identical behaviour from one implementation —
the same reason every surface shares one agent loop.

Commands run *before* the model call and return directly, so `/help` costs
nothing and `/model` doesn't burn a turn.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Callable

SETTING_MODEL = "model"
SETTING_PROVIDER = "provider"
SETTING_ACTIVE = "active_session"


@dataclass
class CommandContext:
    """Everything a command might need, passed in so this module stays
    testable without standing up the whole runtime."""

    session_id: str           # the session actually in use, after any switch
    base_session_id: str      # the surface's own id, where the switch is recorded
    memory: object            # SessionStore
    skills: object            # SkillManager
    curated: object | None    # CuratedMemory, when one is configured
    router: object            # ProviderRouter
    agents_config: dict
    providers_config: dict
    mcp: object | None = None     # MCPManager
    config: object | None = None  # ConfigStore, when writes are allowed


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


def _catalogue(providers_config: dict) -> list[tuple[str, str]]:
    """Every configured (provider, model) as one flat, numbered-friendly list.

    Order follows the config file, which is stable, so the number shown by
    /models is the number /model N selects.
    """
    out: list[tuple[str, str]] = []
    for provider, spec in (providers_config.get("providers") or {}).items():
        for model in (spec or {}).get("models") or []:
            out.append((provider, model["id"] if isinstance(model, dict) else model))
    return out


def _find_model(providers_config: dict, choice: str) -> tuple[str, str] | None:
    """Resolves a number, a bare model id, or provider/model to one entry."""
    catalogue = _catalogue(providers_config)

    if choice.isdigit():
        index = int(choice) - 1
        return catalogue[index] if 0 <= index < len(catalogue) else None

    if "/" in choice:
        provider, _, model = choice.partition("/")
        for entry in catalogue:
            if entry == (provider, model):
                return entry
        # OpenRouter ids contain slashes themselves (qwen/qwen-2.5-coder), so
        # fall through to a plain id match rather than treating that as
        # provider/model.

    matches = [entry for entry in catalogue if entry[1] == choice]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return matches[0]  # same id under several providers; first wins
    return None


def _numbered(catalogue: list[tuple[str, str]], active: tuple[str, str] | None = None) -> str:
    lines = []
    for index, (provider, model) in enumerate(catalogue, start=1):
        marker = " *" if active and (provider, model) == active else "  "
        lines.append(f"{marker}{index:>3}. {provider}/{model}")
    return "\n".join(lines)


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
    catalogue = _catalogue(ctx.providers_config)
    current_model = ctx.memory.get_setting(ctx.session_id, SETTING_MODEL)
    current_provider = ctx.memory.get_setting(ctx.session_id, SETTING_PROVIDER)
    active = (current_provider or "local", current_model) if current_model else None

    if args and args[0] == "add":
        return _model_add(ctx, args[1:])
    if args and args[0] in ("remove", "rm"):
        return _model_remove(ctx, args[1:])

    if not args:
        header = (
            f"Current model: {current_provider or 'local'}/{current_model}"
            if current_model
            else f"Current model: local/{ctx.router.default_local_model()} (default)"
        )
        return (
            f"{header}\n\n{_numbered(catalogue, active)}\n\n"
            "Pick one with /model <number>, or /model default to go back.\n"
            "Add a new one with /model add <provider> <model-id>."
        )

    choice = args[0]
    if choice in ("default", "reset"):
        ctx.memory.set_setting(ctx.session_id, SETTING_MODEL, None)
        ctx.memory.set_setting(ctx.session_id, SETTING_PROVIDER, None)
        return f"Back to the default ({ctx.router.default_local_model()})."

    found = _find_model(ctx.providers_config, choice)
    if found is None:
        return (
            f"No configured model matches '{choice}'.\n\n{_numbered(catalogue)}\n\n"
            "Pick a number, or add it with /model add <provider> <model-id>."
        )

    provider, model = found
    ctx.memory.set_setting(ctx.session_id, SETTING_MODEL, model)
    ctx.memory.set_setting(ctx.session_id, SETTING_PROVIDER, provider)

    note = ""
    spec = (ctx.providers_config.get("providers") or {}).get(provider) or {}
    declared = spec.get("api_keys") or []
    if declared and not any(os.environ.get(entry.get("env", "")) for entry in declared):
        # Say so now rather than letting the next message fail confusingly.
        names = ", ".join(entry.get("env", "?") for entry in declared)
        note = f"\nNote: {provider} has no API key set ({names}). Add one under Keys & tokens first."

    return f"Now using {provider}/{model} for this session.{note}"


def _model_add(ctx: CommandContext, args: list[str]) -> str:
    """Adds a model to providers.yaml from chat.

    Goes through ConfigStore, so the same validation that guards the dashboard
    applies here: a change that wouldn't resolve is refused rather than written.
    """
    if ctx.config is None:
        return "Editing config isn't available from this surface."
    if len(args) < 2:
        providers = ", ".join((ctx.providers_config.get("providers") or {}).keys())
        return f"Usage: /model add <provider> <model-id>\nProviders: {providers}"

    provider, model_id = args[0], args[1]
    providers = ctx.providers_config.get("providers") or {}
    if provider not in providers:
        return f"No provider '{provider}'. Configured: {', '.join(providers) or 'none'}"

    existing = [m["id"] if isinstance(m, dict) else m for m in (providers[provider].get("models") or [])]
    if model_id in existing:
        return f"{provider} already has '{model_id}'."

    import yaml

    try:
        raw = yaml.safe_load(ctx.config.raw("providers.yaml")) or {}
        raw.setdefault("providers", {}).setdefault(provider, {}).setdefault("models", []).append(model_id)
        ctx.config.write("providers.yaml", yaml.safe_dump(raw, sort_keys=False), actor="chat")
    except Exception as exc:
        return f"error: {exc}"

    return (
        f"Added {provider}/{model_id}.\n"
        "Note: editing through chat rewrites providers.yaml, which drops the comments that were "
        "in it. Use /model to select it."
    )


def _model_remove(ctx: CommandContext, args: list[str]) -> str:
    if ctx.config is None:
        return "Editing config isn't available from this surface."
    if len(args) < 2:
        return "Usage: /model remove <provider> <model-id>"

    provider, model_id = args[0], args[1]
    import yaml

    try:
        raw = yaml.safe_load(ctx.config.raw("providers.yaml")) or {}
        models = (raw.get("providers", {}).get(provider) or {}).get("models") or []
        kept = [m for m in models if (m["id"] if isinstance(m, dict) else m) != model_id]
        if len(kept) == len(models):
            return f"{provider} has no model '{model_id}'."
        raw["providers"][provider]["models"] = kept
        ctx.config.write("providers.yaml", yaml.safe_dump(raw, sort_keys=False), actor="chat")
    except Exception as exc:
        # Most likely a fallback chain still points at it; the validator says so.
        return f"error: {exc}"
    return f"Removed {provider}/{model_id}."


def _cmd_models(ctx: CommandContext, args: list[str]) -> str:
    catalogue = _catalogue(ctx.providers_config)
    if not catalogue:
        return "No models configured."
    current = ctx.memory.get_setting(ctx.session_id, SETTING_MODEL)
    provider = ctx.memory.get_setting(ctx.session_id, SETTING_PROVIDER)
    active = (provider or "local", current) if current else None
    return f"Configured models:\n{_numbered(catalogue, active)}\n\nSelect with /model <number>."


def _cmd_session(ctx: CommandContext, args: list[str]) -> str:
    """Show the current session, switch to another, or list them.

    Switching is stored against the *base* session — the CLI's --session, or a
    channel's `telegram:<chat id>` — so a Telegram user can keep several
    conversations and move between them without a second chat.
    """
    if args and args[0] == "list":
        names = ctx.memory.list_sessions()
        if not names:
            return "No sessions yet."
        active = ctx.session_id
        return "Sessions:\n" + "\n".join(
            f"  {'* ' if n == active else '  '}{n} ({c} message{'s' if c != 1 else ''})" for n, c in names
        )

    if args:
        target = args[0].strip()
        if not target.replace("-", "").replace("_", "").replace(":", "").isalnum():
            return "A session name may contain letters, digits, dash, underscore or colon."
        ctx.memory.set_setting(ctx.base_session_id, SETTING_ACTIVE, None if target == ctx.base_session_id else target)
        count = len(ctx.memory.get_history(target))
        return f"Switched to session '{target}' ({count} message(s)). /session default returns to the original."

    history = ctx.memory.get_history(ctx.session_id)
    model = ctx.memory.get_setting(ctx.session_id, SETTING_MODEL)
    lines = [
        f"Session: {ctx.session_id}",
        f"Messages: {len(history)}",
        f"Model override: {model or '(none — using the default)'}",
    ]
    if ctx.session_id != ctx.base_session_id:
        lines.append(f"(switched from '{ctx.base_session_id}')")
    lines.append("Use /session <name> to switch, /session list to see them all.")
    return "\n".join(lines)


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


def _cmd_credential(ctx: CommandContext, args: list[str]) -> str:
    """Manage website logins for the browser tool.

    Adding one from chat works, but the dashboard is the better route: a
    password typed into Telegram still exists in Telegram's own history, and
    on your phone screen, whatever this does afterwards. The command text
    itself never enters yozhan's conversation history — commands are handled
    before anything is stored — and the model never sees the value.
    """
    from yozhan_runtime.credentials import CredentialError, CredentialVault

    action = args[0] if args else "list"
    try:
        vault = CredentialVault()
        if action == "list":
            entries = vault.list()
            if not entries:
                return (
                    "No stored logins. Add one with:\n"
                    "  /credential add <name> <site> <username> <password>\n"
                    "Prefer the dashboard — a password typed in chat also lives in that chat's history."
                )
            lines = ["Stored logins (passwords are never shown):"]
            for entry in entries:
                lines.append(f"  {entry.name:<16} {entry.host:<24} {entry.username}")
            return "\n".join(lines)

        if action == "add":
            if len(args) < 5:
                return "Usage: /credential add <name> <site> <username> <password>"
            info = vault.store(args[1], args[2], args[3], " ".join(args[4:]))
            return (
                f"Stored '{info.name}' for {info.host} as {info.username}.\n"
                f"It will only ever be used on {info.host}. "
                "If you sent this over a chat app, consider changing the password there and re-adding "
                "it from the dashboard — the message is still in that app's history."
            )

        if action in ("remove", "delete"):
            if len(args) < 2:
                return "Usage: /credential remove <name>"
            vault.delete(args[1])
            return f"Removed '{args[1]}'."

        return "Usage: /credential [list|add|remove]"
    except CredentialError as exc:
        return f"error: {exc}"


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
        Command("model", "Show, pick or add a model.", "/model [N|id|add|remove]", _cmd_model),
        Command("models", "List every configured model.", "/models", _cmd_models),
        Command("session", "Show, switch or list sessions.", "/session [name|list]", _cmd_session),
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
        Command(
            "credential",
            "Manage website logins for the browser.",
            "/credential [list|add|remove]",
            _cmd_credential,
        ),
    ]
}

# Aliases for the things people reach for by another name.
ALIASES = {
    "clear": "new",
    "reset": "new",
    "h": "help",
    "?": "help",
    "history": "search",
    "login": "credential",
    "credentials": "credential",
}


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
