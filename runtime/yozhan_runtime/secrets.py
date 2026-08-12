"""Server-side storage for API keys and channel tokens, so they can be managed
from the dashboard instead of by editing the stack and redeploying.

Be clear-eyed about what this is: **plaintext at rest**, in a 0600 file on the
volume. Anyone with root on the box, or a copy of the volume, can read it.
That is not a great deal worse than the alternative — Portainer stores stack
environment variables in plaintext too — but it is worse than not having the
keys on the box at all, and it is a real change in blast radius if the host is
compromised. Encrypting the file only moves the problem to wherever the master
key lives, which on a single-host deployment is the same disk.

The API never returns a stored value. It reports names and whether each is
set; reading one back would turn any dashboard session into a key exfiltration
tool, which rather defeats the point of storing them server-side.

Secrets are merged into os.environ on load, which is what the provider
KeyRing already reads — so nothing downstream needs to know this exists.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from yozhan_runtime.config import data_dir

# Matches how env vars are referenced in providers.yaml.
VALID_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# Names the runtime uses for its own behaviour rather than for talking to a
# provider. Letting these be set from the dashboard would let a UI edit change
# where the runtime reads config or writes files.
RESERVED_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "PYTHONPATH",
        "YOZHAN_CONFIG_DIR",
        "YOZHAN_DATA_DIR",
        "YOZHAN_SKILLS_DIR",
        "YOZHAN_USER_SKILLS_DIR",
        "YOZHAN_WORKSPACE_DIR",
        "LLAMA_SERVER_URL",
        "GATEWAY_ADMIN_TOKEN",
    }
)


class SecretError(ValueError):
    pass


def validate_name(name: str) -> None:
    if not VALID_NAME.match(name or ""):
        raise SecretError(
            "Secret names must be UPPER_SNAKE_CASE, start with a letter, and be at most 64 characters."
        )
    if name in RESERVED_NAMES:
        raise SecretError(f"'{name}' is used by the runtime itself and cannot be set here.")


class SecretStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "secrets.json")
        self._values: dict[str, str] = {}
        self._updated: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretError(f"{self.path} is not valid JSON: {exc}") from exc
        self._values = {k: v for k, v in (raw.get("secrets") or {}).items() if isinstance(v, str)}
        self._updated = raw.get("updated") or {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"secrets": self._values, "updated": self._updated}
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # best effort; some mounts don't support it

    def apply_to_environment(self) -> None:
        """Makes stored secrets visible to the provider router.

        Real environment variables win. If you set a key in the stack *and* in
        the dashboard, the stack is the more explicit statement of intent, and
        silently overriding it would be very confusing to debug.
        """
        for name, value in self._values.items():
            if name not in os.environ or not os.environ[name]:
                os.environ[name] = value

    def set(self, name: str, value: str) -> None:
        validate_name(name)
        if not isinstance(value, str) or not value.strip():
            raise SecretError("Value cannot be empty.")
        self._values[name] = value
        self._updated[name] = datetime.now(timezone.utc).isoformat()
        self._save()
        os.environ[name] = value  # live, so no restart is needed

    def delete(self, name: str) -> None:
        if name not in self._values:
            raise SecretError(f"No stored secret named '{name}'.")
        del self._values[name]
        self._updated.pop(name, None)
        self._save()
        # Only unset the process env if it came from here; a value set in the
        # stack should survive deleting the dashboard copy.
        if os.environ.get(name) is not None and name not in _environ_snapshot:
            os.environ.pop(name, None)

    def describe(self) -> list[dict]:
        """Names and status only — never values."""
        names = set(self._values) | {n for n in _referenced_env_names() if n}
        out = []
        for name in sorted(names):
            from_env = bool(_environ_snapshot.get(name))
            out.append(
                {
                    "name": name,
                    "stored": name in self._values,
                    "from_environment": from_env,
                    "set": bool(os.environ.get(name)),
                    "updated_at": self._updated.get(name),
                }
            )
        return out


# Captured at import, before any stored secret is applied, so we can always
# tell a stack-provided value from a dashboard-provided one.
_environ_snapshot: dict[str, str] = dict(os.environ)


def _referenced_env_names() -> set[str]:
    """Env var names providers.yaml expects, so the UI can show what's missing
    rather than only what's already been set."""
    try:
        from yozhan_runtime.config import load_providers

        providers = load_providers().get("providers") or {}
    except Exception:
        return set()

    names = set()
    for spec in providers.values():
        for entry in (spec or {}).get("api_keys") or []:
            if isinstance(entry, dict) and entry.get("env"):
                names.add(entry["env"])
    return names
