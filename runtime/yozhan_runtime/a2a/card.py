"""The Agent Card: the document another agent fetches to learn what this one
is and how to talk to it, served at /.well-known/agent-card.json.

Only skills explicitly marked `a2a: true` in their manifest are advertised.
Publishing the full skill list by default would leak the shape of a private
deployment to anyone who can reach the endpoint, so exposure is opt-in.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1.0"


def build_agent_card(
    name: str,
    description: str,
    url: str,
    skills: list,
    version: str = "0.1.0",
    requires_auth: bool = True,
) -> dict:
    advertised = [s for s in skills if getattr(s, "a2a", False)]
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": name,
        "description": description,
        "url": url,
        "version": version,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "securitySchemes": (
            {"bearer": {"type": "http", "scheme": "bearer"}} if requires_auth else {}
        ),
        "security": [{"bearer": []}] if requires_auth else [],
        "skills": [
            {
                "id": skill.name,
                "name": skill.name,
                "description": skill.description,
                "tags": skill.tags,
            }
            for skill in advertised
        ],
    }
