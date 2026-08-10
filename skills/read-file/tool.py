"""read-file tool implementation. See SKILL.md for the manifest."""

from __future__ import annotations

import os
from pathlib import Path

NAME = "read_file"
DESCRIPTION = "Read a UTF-8 text file from the local workspace directory."
PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path relative to the workspace root"},
    },
    "required": ["path"],
}

_MAX_BYTES = 65536


def run(path: str) -> str:
    workspace = Path(os.environ.get("YOZHAN_WORKSPACE_DIR", "workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    target = (workspace / path).resolve()
    if workspace != target and workspace not in target.parents:
        return f"error: '{path}' resolves outside the workspace root"
    if not target.is_file():
        return f"error: no such file '{path}' in workspace"

    data = target.read_bytes()
    truncated = len(data) > _MAX_BYTES
    text = data[:_MAX_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += "\n... [truncated]"
    return text
