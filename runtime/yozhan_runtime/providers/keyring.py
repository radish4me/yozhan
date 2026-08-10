"""Resolves and rotates a provider's configured API keys
(config/providers.yaml `api_keys: [{env: NAME}, ...]`). The router rotates
to the next configured key when a call comes back rate-limited or
unauthorized (HTTP 401/403/429) — see ARCHITECTURE.md section 4.1 and
ROADMAP.md Phase 4.
"""

from __future__ import annotations

import os

ROTATE_ON_STATUS = {401, 403, 429}


class KeyRing:
    def __init__(self, provider_name: str, api_keys_config: list[dict]):
        self.provider_name = provider_name
        env_names = [entry["env"] for entry in api_keys_config]
        self._keys = [v for v in (os.environ.get(name) for name in env_names) if v]
        self._cursor = 0

    def __len__(self) -> int:
        return len(self._keys)

    def __bool__(self) -> bool:
        return bool(self._keys)

    def current(self) -> str:
        return self._keys[self._cursor % len(self._keys)]

    def rotate(self) -> None:
        self._cursor += 1
