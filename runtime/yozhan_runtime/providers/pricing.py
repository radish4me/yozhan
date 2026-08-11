"""Token-cost estimation from the optional `pricing:` block a model may carry
in config/providers.yaml:

    models:
      - id: claude-sonnet-5
        pricing: {input_per_mtok: 3.0, output_per_mtok: 15.0}

Models configured as a bare string (the common case) simply have no pricing
and report a cost of None rather than a fabricated zero — an unpriced model
must never look free in the Phase 7 cost report. Local llama.cpp inference is
genuinely $0 and is priced as such explicitly.
"""

from __future__ import annotations


def _model_entries(provider_cfg: dict) -> list[dict]:
    entries = []
    for model in provider_cfg.get("models", []) or []:
        if isinstance(model, dict):
            entries.append(model)
        else:
            entries.append({"id": model})
    return entries


def find_pricing(providers_config: dict, provider: str, model: str | None) -> dict | None:
    provider_cfg = (providers_config.get("providers") or {}).get(provider)
    if provider_cfg is None:
        return None
    if provider_cfg.get("type") == "llama_cpp":
        return {"input_per_mtok": 0.0, "output_per_mtok": 0.0}
    for entry in _model_entries(provider_cfg):
        if entry.get("id") == model:
            return entry.get("pricing")
    return None


def estimate_cost(
    providers_config: dict, provider: str, model: str | None, usage: dict | None
) -> float | None:
    """Returns cost in USD, or None when the model has no configured pricing
    or the provider returned no token usage."""
    if not usage:
        return None
    pricing = find_pricing(providers_config, provider, model)
    if not pricing:
        return None
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    input_rate = pricing.get("input_per_mtok", 0.0)
    output_rate = pricing.get("output_per_mtok", 0.0)
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
