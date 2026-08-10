"""SQLite+FTS5 session/message store — one DB file per user, conversation
history persisted across CLI restarts. Phase 6 adds curated MEMORY.md/USER.md
and a pluggable vector backend behind the same MemoryBackend interface.
See ARCHITECTURE.md section 3.4.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from yozhan_runtime.config import data_dir


class MemoryBackend(ABC):
    @abstractmethod
    def append_message(self, session_id: str, role: str, content: str) -> None: ...

    @abstractmethod
    def get_history(self, session_id: str, limit: int = 50) -> list[dict]: ...

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> list[dict]: ...


class SessionStore(MemoryBackend):
    def __init__(self, user_id: str = "default", db_dir: Path | None = None):
        self.db_dir = db_dir or data_dir()
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"{user_id}.db"
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content, content='messages', content_rowid='id'
            );
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END;
            """
        )
        self._conn.commit()

    def append_message(self, session_id: str, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.session_id, m.role, m.content, m.created_at
            FROM messages_fts f JOIN messages m ON m.id = f.rowid
            WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
