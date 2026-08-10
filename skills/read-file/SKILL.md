---
name: read-file
version: 0.1.0
description: Read a UTF-8 text file from the local workspace directory.
capabilities: [filesystem]
tags: [example, filesystem]
depends_on: []
tool: true
---

# read-file

Reads a text file and returns its contents (truncated if very large). Paths
are resolved relative to the workspace root (`YOZHAN_WORKSPACE_DIR`, defaults
to `./workspace`) — this tool refuses to read anything outside that root.

Real sandboxed execution (the Gateway's containerized tool-execution model
from [ARCHITECTURE.md](../../ARCHITECTURE.md#31-gateway-typescript--node))
lands in Phase 7; until then this tool runs in-process with the workspace-root
allowlist as its only containment.
