"""web-search stub tool implementation. See SKILL.md for the manifest."""

from __future__ import annotations

NAME = "web_search"
DESCRIPTION = "Search the web (stub — no search provider configured yet)."
PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
    },
    "required": ["query"],
}


def run(query: str) -> str:
    return (
        f"web_search is not configured in this deployment (query received: {query!r}). "
        "This is a Phase 2 stub proving the skill/tool format; a real search "
        "provider integration is planned for a later phase."
    )
