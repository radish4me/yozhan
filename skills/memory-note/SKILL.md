---
name: memory-note
version: 0.1.0
description: Record, update, or remove a durable note in cross-session memory (MEMORY.md / USER.md).
capabilities: [memory]
tags: [core, memory]
depends_on: []
tool: true
---

# memory-note

Writes to the user's curated cross-session memory. Use it when you learn
something that will still matter in a *future* conversation — a stable
preference, a project constraint, a correction the user made — not for
details that only matter to the current turn.

## Actions

- `add` — append a note (deduplicated automatically)
- `remove` — drop every note containing the given substring
- `show` — return the current contents

## Which file

- `kind: "memory"` (default) — durable facts, preferences, project context
- `kind: "user"` — who the user is

Both files are size-capped (see `memory/curated.py`). When a write would
exceed the cap the tool returns an error instead of truncating — remove or
condense an existing note rather than growing the file, since every note is
prompt overhead paid on each turn.
