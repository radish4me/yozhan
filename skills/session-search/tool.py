"""session-search tool implementation. See SKILL.md for the manifest."""

from __future__ import annotations

from yozhan_runtime.memory.store import SessionStore

NAME = "session_search"
DESCRIPTION = (
    "Search past conversations for something said earlier. Use when the user refers to a previous "
    "discussion that isn't in the current context."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Words to search for"},
        "limit": {"type": "integer", "description": "Maximum results (default 10)"},
    },
    "required": ["query"],
}


def run(query: str, limit: int = 10) -> str:
    store = SessionStore()
    try:
        # FTS5 treats several characters as operators; a user's words are not a
        # query language, so quote them into a phrase match.
        safe = '"' + query.replace('"', " ") + '"'
        results = store.search(safe, limit=max(1, min(int(limit), 25)))
    except Exception as exc:
        return f"error searching history: {exc}"
    finally:
        store.close()

    if not results:
        return f"No past messages matched {query!r}."

    lines = [f"{len(results)} match(es) for {query!r}:"]
    for row in results:
        when = (row.get("created_at") or "")[:10]
        snippet = row["content"].replace("\n", " ")[:200]
        lines.append(f"[{when} {row['session_id']}] {row['role']}: {snippet}")
    return "\n".join(lines)
