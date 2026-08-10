"""MemoryBackend scaffold. Implemented starting Phase 2 (session/trace store,
SQLite+FTS5) and Phase 6 (curated MEMORY.md/USER.md, learning-loop skill
authoring). See ARCHITECTURE.md section 3.4.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class MemoryBackend(ABC):
    @abstractmethod
    def store(self, key: str, value: dict) -> None: ...

    @abstractmethod
    def retrieve(self, query: str) -> list[dict]: ...
