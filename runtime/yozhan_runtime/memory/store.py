"""SQLite+FTS5 store — one DB file per user. Holds conversation history
(Phase 2), plus execution traces and staged skill proposals that feed the
Phase 6 learning loop and the Phase 7 cost/latency eval reporting.
Curated MEMORY.md/USER.md live alongside in curated.py.
See ARCHITECTURE.md section 3.4.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from yozhan_runtime.config import data_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryBackend(ABC):
    @abstractmethod
    def append_message(self, session_id: str, role: str, content: str) -> None: ...

    @abstractmethod
    def get_history(self, session_id: str, limit: int = 50) -> list[dict]: ...

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> list[dict]: ...

    # Tracing is optional for a backend — a minimal or in-memory implementation
    # can ignore it without breaking the agent loop.
    def append_trace(self, **kwargs) -> None:  # noqa: D401
        return None


class SessionStore(MemoryBackend):
    def __init__(self, user_id: str = "default", db_dir: Path | None = None):
        self.db_dir = db_dir or data_dir()
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"{user_id}.db"
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
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

            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                agent TEXT,
                kind TEXT NOT NULL,
                name TEXT,
                provider TEXT,
                latency_ms REAL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL,
                ok INTEGER NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS traces_task_idx ON traces(task_id);

            CREATE TABLE IF NOT EXISTS session_settings (
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (session_id, key)
            );

            CREATE TABLE IF NOT EXISTS skill_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                action TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                content TEXT NOT NULL,
                rationale TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    # --- conversation history -------------------------------------------

    def append_message(self, session_id: str, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
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

    # --- execution traces -------------------------------------------------

    def append_trace(
        self,
        task_id: str,
        session_id: str,
        kind: str,
        ok: bool,
        agent: str | None = None,
        name: str | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cost_usd: float | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO traces (task_id, session_id, agent, kind, name, provider, latency_ms,
                                prompt_tokens, completion_tokens, cost_usd, ok, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                session_id,
                agent,
                kind,
                name,
                provider,
                latency_ms,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                1 if ok else 0,
                error,
                _now(),
            ),
        )
        self._conn.commit()

    def get_task_traces(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM traces WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_task_ids(self, limit: int = 20) -> list[str]:
        rows = self._conn.execute(
            "SELECT task_id, MAX(id) AS last FROM traces GROUP BY task_id ORDER BY last DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row["task_id"] for row in rows]

    def cost_summary(self, group_by: str = "agent") -> list[dict]:
        """Per-agent (or per-model) totals for the Phase 7 cost/latency view."""
        if group_by not in {"agent", "name", "provider"}:
            raise ValueError(f"unsupported group_by '{group_by}'")
        rows = self._conn.execute(
            f"""
            SELECT COALESCE({group_by}, '(none)') AS key,
                   COUNT(*) AS calls,
                   SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failures,
                   AVG(latency_ms) AS avg_latency_ms,
                   SUM(COALESCE(cost_usd, 0)) AS total_cost_usd,
                   SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)) AS total_tokens
            FROM traces GROUP BY key ORDER BY total_cost_usd DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    # --- per-session settings (slash commands) ----------------------------

    def set_setting(self, session_id: str, key: str, value: str | None) -> None:
        """A per-session override, e.g. the model chosen with /model.

        Stored rather than held in memory because a channel or dashboard turn
        builds a fresh agent each time — there is no long-lived object to keep
        it on.
        """
        if value is None:
            self._conn.execute(
                "DELETE FROM session_settings WHERE session_id = ? AND key = ?", (session_id, key)
            )
        else:
            self._conn.execute(
                "INSERT INTO session_settings (session_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value",
                (session_id, key, value),
            )
        self._conn.commit()

    def get_setting(self, session_id: str, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM session_settings WHERE session_id = ? AND key = ?", (session_id, key)
        ).fetchone()
        return row["value"] if row else None

    def clear_session(self, session_id: str) -> int:
        """Drops a session's conversation history. Traces are kept — they are
        the record of what happened, and the learning loop reads them."""
        cursor = self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.commit()
        return cursor.rowcount

    # --- staged skill proposals (learning loop) ---------------------------

    def add_proposal(
        self, action: str, skill_name: str, content: str, rationale: str, task_id: str | None = None
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO skill_proposals (task_id, action, skill_name, content, rationale, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (task_id, action, skill_name, content, rationale, _now()),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def list_proposals(self, status: str = "pending") -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM skill_proposals WHERE status = ? ORDER BY id ASC", (status,)
        ).fetchall()
        return [dict(row) for row in rows]

    def get_proposal(self, proposal_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM skill_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_proposal_status(self, proposal_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE skill_proposals SET status = ? WHERE id = ?", (status, proposal_id)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
