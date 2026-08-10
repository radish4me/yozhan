"""Resolves an agent's model assignment from config/agents.yaml +
config/providers.yaml, per ARCHITECTURE.md section 4.2: explicit
{provider, model} pin -> named fallback_chain -> defaults.fallback_chain.
Sub-agents resolve independently of their parent.

A pin resolves to a single-entry `chain`. A named sequential fallback_chain
(a YAML list) resolves to `chain`, walked in order by
ProviderRouter.chat_with_fallback() on failure (ROADMAP.md Phase 4). A
`mode: parallel` chain (a YAML mapping with a `members` list) resolves to
`parallel_members` instead, fanned out concurrently by
ProviderRouter.chat_parallel(). Exactly one of chain/parallel_members is
set. `.provider`/`.model` always reflect the primary/first entry, for
display (e.g. `yozhan agents`).
"""

from __future__ import annotations

from dataclasses import dataclass

from yozhan_runtime.config import load_agents, load_providers


class AgentConfigError(RuntimeError):
    pass


@dataclass
class ResolvedAgent:
    name: str
    mode: str
    subagent_of: str | None
    provider: str
    model: str
    sandbox: str
    chain: list[dict] | None = None
    parallel_members: list[dict] | None = None


def resolve_agent(
    agent_name: str,
    agents_config: dict | None = None,
    providers_config: dict | None = None,
) -> ResolvedAgent:
    agents_config = agents_config if agents_config is not None else load_agents()
    providers_config = providers_config if providers_config is not None else load_providers()

    agents = agents_config.get("agents", {})
    if agent_name not in agents:
        raise AgentConfigError(f"no agent named '{agent_name}' in config/agents.yaml")
    spec = agents[agent_name]
    defaults = agents_config.get("defaults", {})

    chain: list[dict] | None = None
    parallel_members: list[dict] | None = None

    if "provider" in spec and "model" in spec:
        provider, model = spec["provider"], spec["model"]
        chain = [{"provider": provider, "model": model}]
    else:
        chain_name = spec.get("fallback_chain", defaults.get("fallback_chain"))
        if not chain_name:
            raise AgentConfigError(
                f"agent '{agent_name}' has no provider/model pin and no fallback_chain to fall back on"
            )
        chains = providers_config.get("fallback_chains", {})
        if chain_name not in chains:
            raise AgentConfigError(
                f"fallback_chain '{chain_name}' referenced by agent '{agent_name}' "
                "not found in config/providers.yaml"
            )
        chain_def = chains[chain_name]
        if isinstance(chain_def, dict) and chain_def.get("mode") == "parallel":
            parallel_members = chain_def.get("members") or []
            if not parallel_members:
                raise AgentConfigError(f"parallel fallback_chain '{chain_name}' has no members")
            provider, model = parallel_members[0]["provider"], parallel_members[0]["model"]
        else:
            chain = chain_def or []
            if not chain:
                raise AgentConfigError(f"fallback_chain '{chain_name}' is empty")
            provider, model = chain[0]["provider"], chain[0]["model"]

    return ResolvedAgent(
        name=agent_name,
        mode=spec.get("mode", "on-demand"),
        subagent_of=spec.get("subagent_of"),
        provider=provider,
        model=model,
        sandbox=spec.get("sandbox", defaults.get("sandbox", "non-privileged-only")),
        chain=chain,
        parallel_members=parallel_members,
    )
