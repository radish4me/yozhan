from yozhan_runtime.providers.pricing import estimate_cost, find_pricing

CONFIG = {
    "providers": {
        "local": {"type": "llama_cpp", "models": [{"id": "qwen3.5-0.8b"}]},
        "anthropic": {
            "type": "anthropic",
            "models": [
                {"id": "claude-sonnet-5", "pricing": {"input_per_mtok": 3.0, "output_per_mtok": 15.0}},
                "claude-haiku-4-5",  # bare string: no pricing configured
            ],
        },
    }
}

USAGE = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}


def test_priced_model_computes_cost():
    assert estimate_cost(CONFIG, "anthropic", "claude-sonnet-5", USAGE) == 18.0


def test_local_inference_is_free_not_unknown():
    assert estimate_cost(CONFIG, "local", "qwen3.5-0.8b", USAGE) == 0.0


def test_unpriced_model_reports_unknown_rather_than_zero():
    # An unpriced remote model must not look free in the cost report.
    assert estimate_cost(CONFIG, "anthropic", "claude-haiku-4-5", USAGE) is None


def test_missing_usage_yields_no_cost():
    assert estimate_cost(CONFIG, "anthropic", "claude-sonnet-5", None) is None


def test_unknown_provider_yields_no_pricing():
    assert find_pricing(CONFIG, "nope", "whatever") is None


def test_partial_usage_counts_only_what_is_present():
    cost = estimate_cost(CONFIG, "anthropic", "claude-sonnet-5", {"prompt_tokens": 1_000_000})
    assert cost == 3.0
