"""Decides, per tool invocation, whether it runs in-process or in a sandbox.

Modes (config/agents.yaml `defaults.sandbox` or a per-agent `sandbox:`):

  off                  everything runs in-process
  non-privileged-only  sandbox everything except skills marked `elevated: true`
  all                  sandbox everything, including elevated skills

A skill declares `elevated: true` in its SKILL.md frontmatter when it
legitimately needs the runtime's own process — memory-note, for instance,
writes to the user's curated memory outside the workspace. Marking a skill
elevated is a deliberate trust decision, which is why it lives in the
manifest and not in the tool code.
"""

from __future__ import annotations

from dataclasses import dataclass

from yozhan_runtime.sandbox.backends import DockerSandbox, SubprocessSandbox
from yozhan_runtime.sandbox.types import Sandbox

MODES = ("off", "non-privileged-only", "all")

_BACKENDS = {
    "subprocess": SubprocessSandbox,
    "docker": DockerSandbox,
    "podman": lambda: DockerSandbox(runtime_cmd="podman"),
}


@dataclass
class SandboxPolicy:
    mode: str = "non-privileged-only"
    sandbox: Sandbox | None = None
    timeout_seconds: int = 30

    def should_sandbox(self, elevated: bool) -> bool:
        if self.mode == "off" or self.sandbox is None:
            return False
        if self.mode == "all":
            return True
        return not elevated


def build_backend(name: str) -> Sandbox:
    factory = _BACKENDS.get(name)
    if factory is None:
        raise ValueError(f"unknown sandbox backend '{name}' (expected one of {', '.join(_BACKENDS)})")
    return factory()


def sandbox_from_config(agents_config: dict, agent_name: str | None = None) -> SandboxPolicy:
    """Resolves the effective sandbox policy for an agent: its own `sandbox:`
    setting if present, else `defaults.sandbox`."""
    defaults = agents_config.get("defaults", {}) or {}
    mode = defaults.get("sandbox", "non-privileged-only")
    if agent_name:
        spec = (agents_config.get("agents", {}) or {}).get(agent_name, {}) or {}
        mode = spec.get("sandbox", mode)

    if mode not in MODES:
        raise ValueError(f"invalid sandbox mode '{mode}' (expected one of {', '.join(MODES)})")

    backend_name = defaults.get("sandbox_backend", "subprocess")
    timeout = int(defaults.get("sandbox_timeout_seconds", 30))
    backend = None if mode == "off" else build_backend(backend_name)
    return SandboxPolicy(mode=mode, sandbox=backend, timeout_seconds=timeout)
