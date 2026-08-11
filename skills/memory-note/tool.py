"""memory-note tool implementation. See SKILL.md for the manifest."""

from __future__ import annotations

from yozhan_runtime.memory.curated import CuratedMemory, MemoryCapExceeded

NAME = "memory_note"
DESCRIPTION = (
    "Record, update, or remove a durable note in cross-session memory. Use for facts that will "
    "still matter in a future conversation, not details specific to the current turn."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["add", "remove", "show"]},
        "note": {"type": "string", "description": "Note text to add, or substring to remove"},
        "kind": {"type": "string", "enum": ["memory", "user"], "description": "Defaults to 'memory'"},
    },
    "required": ["action"],
}


def run(action: str, note: str | None = None, kind: str = "memory") -> str:
    memory = CuratedMemory()
    try:
        if action == "show":
            return memory.read(kind) or f"({kind} memory is empty)"
        if action == "add":
            if not note:
                return "error: 'add' requires a note"
            memory.add(note, kind)
            return f"recorded in {kind} memory: {note}"
        if action == "remove":
            if not note:
                return "error: 'remove' requires the substring to remove"
            memory.remove(note, kind)
            return f"removed notes matching {note!r} from {kind} memory"
        return f"error: unknown action '{action}'"
    except MemoryCapExceeded as exc:
        return f"error: {exc}"
