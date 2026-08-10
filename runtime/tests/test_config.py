import os
from pathlib import Path

os.environ.setdefault("YOZHAN_CONFIG_DIR", str(Path(__file__).resolve().parents[2] / "config"))

from yozhan_runtime.config import load_agents, load_providers  # noqa: E402


def test_load_providers_has_local_default():
    config = load_providers()
    assert config["providers"]["local"]["default_model"] == "qwen3.5-0.8b"


def test_load_agents_has_orchestrator():
    config = load_agents()
    assert "orchestrator" in config["agents"]
