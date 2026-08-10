---
name: example-echo
version: 0.1.0
description: Trivial example skill proving the SKILL.md format end-to-end. Echoes its input back.
capabilities: [text]
tags: [example]
depends_on: []
---

# example-echo

A minimal skill used to validate skill discovery and the
[agentskills.io](https://agentskills.io/specification)-compatible manifest
format described in [ARCHITECTURE.md](../../ARCHITECTURE.md#33-skill--tool-layer-python-shared).

## Procedure

1. Take the user's input text.
2. Return it unchanged, prefixed with `echo: `.

No external tool implementation is required for this skill — it's handled
directly by the agent runtime as a smoke test for skill loading (wired up in
Phase 2, see [ROADMAP.md](../../ROADMAP.md)).
