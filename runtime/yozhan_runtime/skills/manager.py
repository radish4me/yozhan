"""SkillManager: discovers SKILL.md (agentskills.io-format) directories under
skills/ and ~/.yozhan/skills/. A skill whose frontmatter sets `tool: true`
also loads a sibling tool.py exposing NAME/DESCRIPTION/PARAMETERS/run(),
which is what gets exposed to the model as an OpenAI-style callable tool.
Skills without `tool: true` are instruction-only (loaded but not callable) —
that plumbing is what ROADMAP.md's Phase 6 learning loop writes/patches.
See ARCHITECTURE.md section 3.3.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from yozhan_runtime.sandbox.policy import SandboxPolicy

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    version: str
    description: str
    capabilities: list[str]
    tags: list[str]
    depends_on: list[str]
    instructions: str
    path: Path
    tool_name: str | None = None
    tool_description: str | None = None
    tool_parameters: dict | None = None
    tool_run: Callable[..., str] | None = field(default=None, repr=False)
    tool_path: Path | None = None
    elevated: bool = False

    def as_openai_tool(self) -> dict | None:
        if not self.tool_name:
            return None
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.tool_description or self.description,
                "parameters": self.tool_parameters or {"type": "object", "properties": {}},
            },
        }


class SkillManager:
    def __init__(self, skill_dirs: list[Path], sandbox_policy: "SandboxPolicy | None" = None):
        self.skill_dirs = skill_dirs
        self.sandbox_policy = sandbox_policy
        self._skills: dict[str, Skill] = {}
        self._tool_index: dict[str, Skill] = {}

    def discover(self) -> list[Skill]:
        self._skills.clear()
        self._tool_index.clear()
        for base in self.skill_dirs:
            if not base.is_dir():
                continue
            for skill_dir in sorted(p for p in base.iterdir() if p.is_dir()):
                manifest_path = skill_dir / "SKILL.md"
                if not manifest_path.is_file():
                    continue
                skill = self._load_skill(skill_dir, manifest_path)
                if skill is None:
                    continue
                self._skills[skill.name] = skill
                if skill.tool_name:
                    self._tool_index[skill.tool_name] = skill
        return list(self._skills.values())

    def _load_skill(self, skill_dir: Path, manifest_path: Path) -> Skill | None:
        raw = manifest_path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(raw)
        if not match:
            return None
        frontmatter = yaml.safe_load(match.group(1)) or {}
        body = match.group(2).strip()

        skill = Skill(
            name=frontmatter["name"],
            version=str(frontmatter.get("version", "0.0.0")),
            description=frontmatter.get("description", ""),
            capabilities=frontmatter.get("capabilities", []),
            tags=frontmatter.get("tags", []),
            depends_on=frontmatter.get("depends_on", []),
            instructions=body,
            path=skill_dir,
            elevated=bool(frontmatter.get("elevated", False)),
        )

        if frontmatter.get("tool"):
            tool_path = skill_dir / "tool.py"
            if tool_path.is_file():
                module = self._load_tool_module(skill.name, tool_path)
                skill.tool_name = getattr(module, "NAME", skill.name)
                skill.tool_description = getattr(module, "DESCRIPTION", skill.description)
                skill.tool_parameters = getattr(module, "PARAMETERS", None)
                skill.tool_run = getattr(module, "run", None)
                skill.tool_path = tool_path

        return skill

    @staticmethod
    def _load_tool_module(skill_name: str, tool_path: Path):
        spec = importlib.util.spec_from_file_location(f"yozhan_skill_{skill_name}", tool_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def discovered(self) -> list[Skill]:
        """Skills loaded by the last discover() call, without re-scanning disk."""
        return list(self._skills.values())

    def as_openai_tools(self) -> list[dict]:
        return [s.as_openai_tool() for s in self._skills.values() if s.tool_name]

    def execute(self, tool_name: str, arguments: dict) -> str:
        skill = self._tool_index.get(tool_name)
        if skill is None or skill.tool_run is None:
            return f"error: unknown tool '{tool_name}'"

        policy = self.sandbox_policy
        if policy is not None and skill.tool_path and policy.should_sandbox(skill.elevated):
            result = policy.sandbox.run_tool(
                str(skill.tool_path), arguments, timeout=policy.timeout_seconds
            )
            return result.as_tool_output()

        try:
            return str(skill.tool_run(**arguments))
        except Exception as exc:  # never let one bad tool crash the agent loop
            return f"error running tool '{tool_name}': {exc}"
