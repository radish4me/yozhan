"""a2a-peer tool implementation. See SKILL.md for the manifest."""

from __future__ import annotations

import json

from yozhan_runtime.a2a.client import A2AClient, A2AError, load_peers
from yozhan_runtime.config import load_agents

NAME = "a2a_peer"
DESCRIPTION = (
    "Ask another agent (an A2A peer) a question, list configured peers, or fetch a peer's "
    "agent card. Only peers named in config are reachable."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "discover", "ask"]},
        "peer": {"type": "string", "description": "Configured peer name (required for discover/ask)"},
        "message": {"type": "string", "description": "Message to send (required for ask)"},
    },
    "required": ["action"],
}


def run(action: str, peer: str | None = None, message: str | None = None) -> str:
    a2a_config = load_agents().get("a2a") or {}
    if not a2a_config.get("enabled", False):
        return "error: A2A is disabled — set a2a.enabled: true in config/agents.yaml"

    client = A2AClient(load_peers(a2a_config))

    try:
        if action == "list":
            peers = client.list_peers()
            return "configured peers: " + (", ".join(peers) if peers else "(none)")
        if action == "discover":
            if not peer:
                return "error: 'discover' requires a peer name"
            return json.dumps(client.discover(peer), indent=2)
        if action == "ask":
            if not peer or not message:
                return "error: 'ask' requires both a peer name and a message"
            return client.call(peer, message)
        return f"error: unknown action '{action}'"
    except A2AError as exc:
        return f"error: {exc}"
