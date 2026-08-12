"""Curated cross-session memory: two small, human-readable Markdown files per
user that are injected into the agent's context at session start.

  MEMORY.md — durable facts, preferences, project context
  USER.md   — who the user is

Both are size-capped on purpose: they're prompt overhead paid on *every*
turn, and an unbounded memory file silently degrades into noise. Writes go
through the explicit `memory` tool (skills/memory-note/) rather than being
rewritten silently by the model. See ARCHITECTURE.md section 3.4 and
ROADMAP.md Phase 6.
"""

from __future__ import annotations

from pathlib import Path

from yozhan_runtime.config import data_dir

MEMORY_CAP_CHARS = 2000
USER_CAP_CHARS = 1000


class MemoryCapExceeded(RuntimeError):
    pass


class CuratedMemory:
    def __init__(self, user_id: str = "default", base_dir: Path | None = None):
        self.dir = (base_dir or data_dir()) / "memory" / user_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.dir / "MEMORY.md"
        self.user_path = self.dir / "USER.md"

    def _path_for(self, kind: str) -> tuple[Path, int]:
        if kind == "memory":
            return self.memory_path, MEMORY_CAP_CHARS
        if kind == "user":
            return self.user_path, USER_CAP_CHARS
        raise ValueError(f"unknown memory kind '{kind}' (expected 'memory' or 'user')")

    def read(self, kind: str = "memory") -> str:
        path, _ = self._path_for(kind)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def write(self, content: str, kind: str = "memory") -> None:
        path, cap = self._path_for(kind)
        content = content.strip()
        if len(content) > cap:
            filename = "MEMORY.md" if kind == "memory" else "USER.md"
            raise MemoryCapExceeded(
                f"{filename} would be {len(content)} chars, over the {cap}-char cap — "
                "remove or condense an entry instead of growing the file"
            )
        path.write_text(content + "\n" if content else "", encoding="utf-8")

    def add(self, note: str, kind: str = "memory") -> str:
        """Appends a bullet. Returns the resulting file contents."""
        note = note.strip().lstrip("-").strip()
        existing = self.read(kind).rstrip()
        lines = [line for line in existing.splitlines() if line.strip()]
        if any(line.strip().lstrip("-").strip() == note for line in lines):
            return existing  # already recorded; adding it twice is just prompt bloat
        lines.append(f"- {note}")
        updated = "\n".join(lines)
        self.write(updated, kind)
        return updated

    def remove(self, substring: str, kind: str = "memory") -> str:
        existing = self.read(kind)
        kept = [line for line in existing.splitlines() if line.strip() and substring not in line]
        updated = "\n".join(kept)
        self.write(updated, kind)
        return updated

    def as_system_prompt(self) -> str | None:
        """The block injected at session start, or None when nothing is recorded."""
        sections = []
        user = self.read("user").strip()
        memory = self.read("memory").strip()
        if user:
            sections.append(f"What you know about the user:\n{user}")
        if memory:
            sections.append(f"Durable notes from previous sessions:\n{memory}")
        if not sections:
            return None
        return "\n\n".join(sections)
