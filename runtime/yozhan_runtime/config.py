"""Loads config/providers.yaml and config/agents.yaml with ${VAR:-default} interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")


def _interpolate(value: str) -> str:
    def replace(match: re.Match) -> str:
        var_name, _, default = match.groups()
        return os.environ.get(var_name, default or "")

    return _ENV_PATTERN.sub(replace, value)


def _walk(node):
    if isinstance(node, dict):
        return {k: _walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v) for v in node]
    if isinstance(node, str):
        return _interpolate(node)
    return node


def config_dir() -> Path:
    return Path(os.environ.get("YOZHAN_CONFIG_DIR", "config"))


def load_yaml(name: str) -> dict:
    path = config_dir() / name
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return _walk(raw)


def load_providers() -> dict:
    return load_yaml("providers.yaml")


def load_agents() -> dict:
    return load_yaml("agents.yaml")
