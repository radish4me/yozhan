"""BaseAgent scaffold. Implemented starting Phase 2 (ROADMAP.md) — on-demand,
scheduled, and continuous execution modes, orchestrator fan-out, and the
config/agents.yaml model-assignment resolution described in ARCHITECTURE.md
section 4.2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AgentResult:
    output: str
    metadata: dict


class BaseAgent(ABC):
    name: str
    mode: str  # "on-demand" | "scheduled" | "continuous"

    @abstractmethod
    def run(self, task: str, context: dict | None = None) -> AgentResult:
        raise NotImplementedError
