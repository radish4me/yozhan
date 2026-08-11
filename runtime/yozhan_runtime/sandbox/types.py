"""Sandbox interface + the environment allowlist shared by every backend.

The single most important thing a sandbox does here is *not* hand a tool the
parent process's environment. The runtime holds provider API keys in env vars
(ANTHROPIC_API_KEY_1, ...); a skill authored by the learning loop or installed
from a community repo has no business reading them. Every backend builds the
child environment from ALLOWED_ENV only.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

# Deliberately minimal. Anything not listed here — every *_API_KEY, HF_TOKEN,
# GATEWAY_ADMIN_TOKEN, TELEGRAM_BOT_TOKEN — never reaches a sandboxed tool.
ALLOWED_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "PYTHONPATH",
    "YOZHAN_WORKSPACE_DIR",
)

DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class SandboxResult:
    ok: bool
    output: str

    def as_tool_output(self) -> str:
        """Tool results are plain strings to the agent loop; a sandbox failure
        is surfaced the same way any other tool error is."""
        return self.output if self.ok else f"error: {self.output}"


def child_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {name: os.environ[name] for name in ALLOWED_ENV if name in os.environ}
    if extra:
        env.update(extra)
    return env


class Sandbox(ABC):
    """Runs one tool invocation in isolation from the runtime process."""

    name: str

    @abstractmethod
    def run_tool(self, tool_path: str, arguments: dict, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> SandboxResult:
        raise NotImplementedError
