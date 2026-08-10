"""SkillManager scaffold. Implemented starting Phase 2 (ROADMAP.md) — discovers
SKILL.md (agentskills.io-format) directories under skills/ and
~/.yozhan/skills/, and exposes them to the orchestrator as callable tools.
See ARCHITECTURE.md section 3.3.
"""

from __future__ import annotations

from pathlib import Path


class SkillManager:
    def __init__(self, skill_dirs: list[Path]):
        self.skill_dirs = skill_dirs

    def discover(self) -> list[dict]:
        raise NotImplementedError("skill discovery lands in Phase 2")
