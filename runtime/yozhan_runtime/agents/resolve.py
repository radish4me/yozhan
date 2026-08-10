"""Resolves an agent's (provider, model) from config/agents.yaml +
config/providers.yaml, per the order defined in ARCHITECTURE.md section 4.2:
explicit {provider, model} pin -> named fallback_chain's first entry ->
defaults.fallback_chain's first entry. Sub-agents resolve independently of
their parent — nothing cascades unless the child omits its own setting.

Only the *primary* entry of a fallback chain is resolved here — walking the
rest of the chain on error, rotating keys, and running `mode: parallel`
chains concurrently are Phase 4 scope (ROADMAP.md); this module only needs
to answer "which (provider, model) does this agent use right now."
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

    if "provider" in spec and "model" in spec:
        provider, model = spec["provider"], spec["model"]
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
        chain = chains[chain_name]
        entries = chain["members"] if isinstance(chain, dict) and chain.get("mode") == "parallel" else chain
        if not entries:
            raise AgentConfigError(f"fallback_chain '{chain_name}' is empty")
        provider, model = entries[0]["provider"], entries[0]["model"]

    return ResolvedAgent(
        name=agent_name,
        mode=spec.get("mode", "on-demand"),
        subagent_of=spec.get("subagent_of"),
        provider=provider,
        model=model,
        sandbox=spec.get("sandbox", defaults.get("sandbox", "non-privileged-only")),
    )
