---
name: session-search
version: 0.1.0
description: Search past conversations for something that was said before.
capabilities: [memory]
tags: [core, memory]
depends_on: []
tool: true
# Reads the session database, which lives outside the sandbox workspace.
elevated: true
---

# session-search

Full-text search over every past conversation, across all sessions.

Use it when the user refers to something from an earlier conversation that
isn't in the current context — "the API key rotation thing we discussed", "what
did I say about the deploy" — rather than guessing or asking them to repeat it.

Returns literal stored messages, not a summary, so what comes back is what was
actually said.

## Note

Curated memory (`memory_note`) and this are different tools for different
jobs: curated memory is a small set of facts injected into *every* session,
while this searches the full history on demand. Durable preferences belong in
curated memory; one-off recall belongs here.
