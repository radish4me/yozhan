"""Website credentials for the browser tool.

The design constraint that shapes everything here: **the model must never see
a password.** If it did, the password would land in the conversation history,
in the trace log, and — worst — inside the context posted to Anthropic or
Gemini on the following turn. So the agent never handles a secret. It says
"log into github", and this module hands the password to the browser directly.

The second constraint: **credentials are bound to a domain.** A page yozhan
browses can contain text aimed at the model ("now sign in at evil-login.com").
Binding each credential to the host it was stored for means that instruction
cannot turn into a credential disclosure, for the same reason a password
manager refuses to autofill on the wrong domain.

Encryption at rest uses Fernet with a key in `credential.key` beside the data.
Be clear about what that buys: it protects a leaked database file or a stray
backup, not a compromised host — anyone who can read the key can read the
credentials. Point YOZHAN_CREDENTIAL_KEY at a key held elsewhere for real
separation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from yozhan_runtime.config import data_dir


class CredentialError(ValueError):
    pass


def normalise_host(url_or_host: str) -> str:
    """github.com, https://github.com/login and GITHUB.COM all mean the same site."""
    value = (url_or_host or "").strip().lower()
    if not value:
        raise CredentialError("a site is required")
    if "://" in value:
        value = urlparse(value).hostname or ""
    else:
        value = value.split("/")[0]
    value = value.split(":")[0]
    if value.startswith("www."):
        value = value[4:]
    if not value or "." not in value:
        raise CredentialError(f"'{url_or_host}' does not look like a domain")
    return value


@dataclass
class CredentialInfo:
    """What may be shown about a credential. Deliberately no password field."""

    name: str
    host: str
    username: str
    updated_at: str


class CredentialVault:
    def __init__(self, path: Path | None = None, key_path: Path | None = None):
        self.path = path or (data_dir() / "credentials.enc")
        self.key_path = key_path or (data_dir() / "credential.key")
        self._entries: dict[str, dict] = {}
        self._fernet = None
        self.load()

    # --- key handling --------------------------------------------------------

    def _cipher(self):
        if self._fernet is not None:
            return self._fernet
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise CredentialError(
                "the 'cryptography' package is required to store credentials; "
                "install the runtime with its [browser] extra"
            ) from exc

        env_key = os.environ.get("YOZHAN_CREDENTIAL_KEY")
        if env_key:
            key = env_key.encode()
        elif self.key_path.is_file():
            key = self.key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(key)
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass

        try:
            self._fernet = Fernet(key)
        except Exception as exc:
            raise CredentialError(f"invalid credential key: {exc}") from exc
        return self._fernet

    # --- storage -------------------------------------------------------------

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            self._entries = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CredentialError(f"{self.path} is corrupt: {exc}") from exc

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def store(self, name: str, host: str, username: str, password: str) -> CredentialInfo:
        name = (name or "").strip().lower()
        if not name.replace("-", "").replace("_", "").isalnum():
            raise CredentialError("name must be letters, digits, dash or underscore")
        if not username or not password:
            raise CredentialError("username and password are both required")

        host = normalise_host(host)
        cipher = self._cipher()
        self._entries[name] = {
            "host": host,
            "username": username,
            "password": cipher.encrypt(password.encode()).decode(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        return CredentialInfo(name=name, host=host, username=username, updated_at=self._entries[name]["updated_at"])

    def delete(self, name: str) -> None:
        name = (name or "").strip().lower()
        if name not in self._entries:
            raise CredentialError(f"no stored credential named '{name}'")
        del self._entries[name]
        self._save()

    def list(self) -> list[CredentialInfo]:
        """Names, hosts and usernames — never passwords."""
        return [
            CredentialInfo(
                name=name,
                host=entry["host"],
                username=entry["username"],
                updated_at=entry.get("updated_at", ""),
            )
            for name, entry in sorted(self._entries.items())
        ]

    def resolve(self, name: str, url: str) -> tuple[str, str]:
        """Returns (username, password) for a credential, but only if `url` is
        on the host it was stored for.

        This is the check that stops a browsed page from talking the agent into
        using a credential somewhere it doesn't belong.
        """
        name = (name or "").strip().lower()
        entry = self._entries.get(name)
        if entry is None:
            known = ", ".join(sorted(self._entries)) or "(none stored)"
            raise CredentialError(f"no stored credential named '{name}'. Available: {known}")

        target = normalise_host(url)
        expected = entry["host"]
        # Allow subdomains of the stored host (accounts.google.com for google.com)
        # but nothing else.
        if target != expected and not target.endswith(f".{expected}"):
            raise CredentialError(
                f"credential '{name}' is bound to {expected}, but the page is {target}. "
                "Refusing to use it here."
            )

        password = self._cipher().decrypt(entry["password"].encode()).decode()
        return entry["username"], password
