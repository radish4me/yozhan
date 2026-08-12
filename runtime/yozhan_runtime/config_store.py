"""Reading and writing config/providers.yaml and config/agents.yaml at runtime.

Three things matter here, and each exists because of a specific way this can
go wrong:

1. **Validation before writing.** A config saved from a form or a text box can
   reference a fallback chain that doesn't exist, or a provider that was just
   deleted. Writing that file makes every subsequent task fail, and the only
   way back is a shell on the server. So a write is validated by actually
   resolving every agent against the proposed config, and rejected with the
   specific reason if that fails.

2. **Atomic writes plus a backup.** A half-written YAML file is a broken
   deployment. Writes go to a temp file and are renamed into place, and the
   previous version is kept so a bad-but-valid change can be rolled back from
   the UI rather than over SSH.

3. **Reload on change.** The server used to read config once at import, so an
   edit did nothing until a restart. Reads here re-check the file's mtime and
   reparse when it moves.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from yozhan_runtime.config import _walk, config_dir, data_dir

CONFIG_FILES = ("providers.yaml", "agents.yaml")
MAX_BACKUPS = 20


class ConfigValidationError(ValueError):
    """Raised when a proposed config would break the deployment."""


@dataclass
class Backup:
    id: str
    file: str
    created_at: str
    size: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_pair(agents: dict, providers: dict) -> None:
    """Checks a (agents, providers) pair the way the runtime will actually use
    it. Deliberately runs the real resolver rather than a schema check — a
    schema can't tell you that `fallback_chain: local_frist` is a typo."""
    # Imported here to avoid a circular import at module load.
    from yozhan_runtime.agents.resolve import AgentConfigError, resolve_agent

    if not isinstance(providers, dict) or not isinstance(agents, dict):
        raise ConfigValidationError("config must be a YAML mapping at the top level")

    provider_map = providers.get("providers")
    if not isinstance(provider_map, dict) or not provider_map:
        raise ConfigValidationError("providers.yaml must define at least one provider under `providers:`")

    for name, spec in provider_map.items():
        if not isinstance(spec, dict):
            raise ConfigValidationError(f"provider '{name}' must be a mapping")
        if not spec.get("type"):
            raise ConfigValidationError(f"provider '{name}' is missing `type:`")

    chains = providers.get("fallback_chains") or {}
    if not isinstance(chains, dict):
        raise ConfigValidationError("`fallback_chains:` must be a mapping of name -> chain")

    def declared_models(provider: str) -> list[str]:
        spec = provider_map.get(provider) or {}
        return [m["id"] if isinstance(m, dict) else m for m in (spec.get("models") or [])]

    for chain_name, chain in chains.items():
        entries = chain.get("members") if isinstance(chain, dict) else chain
        if not entries:
            raise ConfigValidationError(f"fallback chain '{chain_name}' is empty")
        for entry in entries:
            if not isinstance(entry, dict) or "provider" not in entry:
                raise ConfigValidationError(f"every entry in chain '{chain_name}' needs a `provider`")
            if entry["provider"] not in provider_map:
                raise ConfigValidationError(
                    f"chain '{chain_name}' references unknown provider '{entry['provider']}'"
                )
            # A chain pointing at a model the provider doesn't list is almost
            # always a deletion or a typo. Catching it here is the difference
            # between a clear refusal now and a puzzling failure at dispatch.
            model = entry.get("model")
            known = declared_models(entry["provider"])
            if model and known and model not in known:
                raise ConfigValidationError(
                    f"chain '{chain_name}' references '{entry['provider']}/{model}', which that "
                    f"provider does not list. Available: {', '.join(known)}"
                )

    agent_map = agents.get("agents")
    if not isinstance(agent_map, dict) or not agent_map:
        raise ConfigValidationError("agents.yaml must define at least one agent under `agents:`")

    for agent_name in agent_map:
        try:
            resolved = resolve_agent(agent_name, agents, providers)
        except AgentConfigError as exc:
            raise ConfigValidationError(str(exc)) from exc
        if resolved.provider not in provider_map:
            raise ConfigValidationError(
                f"agent '{agent_name}' resolves to unknown provider '{resolved.provider}'"
            )

    sandbox_mode = (agents.get("defaults") or {}).get("sandbox", "non-privileged-only")
    if sandbox_mode not in ("off", "non-privileged-only", "all"):
        raise ConfigValidationError(
            f"defaults.sandbox must be off, non-privileged-only or all (got '{sandbox_mode}')"
        )


class ConfigStore:
    def __init__(self, directory: Path | None = None, backup_dir: Path | None = None):
        self.dir = directory or config_dir()
        self.backup_dir = backup_dir or (data_dir() / "config-backups")
        self._cache: dict[str, dict] = {}
        self._mtimes: dict[str, float] = {}

    def path(self, name: str) -> Path:
        if name not in CONFIG_FILES:
            raise ValueError(f"unknown config file '{name}'")
        return self.dir / name

    # --- reading -------------------------------------------------------------

    def raw(self, name: str) -> str:
        return self.path(name).read_text(encoding="utf-8")

    def get(self, name: str) -> dict:
        """Parsed config, reparsed whenever the file changes on disk."""
        path = self.path(name)
        mtime = path.stat().st_mtime
        if self._mtimes.get(name) != mtime or name not in self._cache:
            self._cache[name] = _walk(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
            self._mtimes[name] = mtime
        return self._cache[name]

    def providers(self) -> dict:
        return self.get("providers.yaml")

    def agents(self) -> dict:
        return self.get("agents.yaml")

    def invalidate(self) -> None:
        self._cache.clear()
        self._mtimes.clear()

    # --- writing -------------------------------------------------------------

    def validate_candidate(self, name: str, text: str) -> dict:
        """Parses and fully validates a proposed file against its counterpart."""
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigValidationError(f"invalid YAML: {exc}") from exc
        if parsed is None:
            raise ConfigValidationError("file is empty")

        # Interpolate exactly as a real load would, so `${VAR:-default}` in the
        # candidate is checked in its resolved form rather than as raw text.
        resolved = _walk(parsed)
        if name == "providers.yaml":
            validate_pair(self.agents(), resolved)
        else:
            validate_pair(resolved, self.providers())
        return resolved

    def write(self, name: str, text: str, actor: str = "unknown") -> dict:
        """Validates, backs up the current version, then writes atomically."""
        parsed = self.validate_candidate(name, text)

        path = self.path(name)
        backup_id = self._backup(name)

        tmp = path.with_suffix(f"{path.suffix}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)  # atomic: readers never see a partial file

        self.invalidate()
        self._audit(name, actor, backup_id)
        return parsed

    def _backup(self, name: str) -> str | None:
        path = self.path(name)
        if not path.is_file():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup_id = f"{name}.{stamp}"
        shutil.copy2(path, self.backup_dir / backup_id)
        self._prune_backups(name)
        return backup_id

    def _prune_backups(self, name: str) -> None:
        existing = sorted(self.backup_dir.glob(f"{name}.*"))
        for stale in existing[:-MAX_BACKUPS]:
            stale.unlink(missing_ok=True)

    def list_backups(self, name: str | None = None) -> list[Backup]:
        if not self.backup_dir.is_dir():
            return []
        pattern = f"{name}.*" if name else "*.yaml.*"
        out = []
        for path in sorted(self.backup_dir.glob(pattern), reverse=True):
            stat = path.stat()
            out.append(
                Backup(
                    id=path.name,
                    file=path.name.split(".yaml.")[0] + ".yaml",
                    created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    size=stat.st_size,
                )
            )
        return out

    def read_backup(self, backup_id: str) -> str:
        path = self._safe_backup_path(backup_id)
        return path.read_text(encoding="utf-8")

    def restore(self, backup_id: str, actor: str = "unknown") -> dict:
        path = self._safe_backup_path(backup_id)
        name = path.name.split(".yaml.")[0] + ".yaml"
        # Restoring goes through write(), so a backup that is no longer valid
        # against the *current* counterpart file is rejected rather than
        # silently reintroducing a broken state.
        return self.write(name, path.read_text(encoding="utf-8"), actor=actor)

    def _safe_backup_path(self, backup_id: str) -> Path:
        # backup_id comes from an HTTP path; refuse anything that could escape
        # the backup directory.
        candidate = (self.backup_dir / backup_id).resolve()
        if candidate.parent != self.backup_dir.resolve() or not candidate.is_file():
            raise ValueError(f"no such backup '{backup_id}'")
        return candidate

    # --- audit ---------------------------------------------------------------

    def _audit(self, name: str, actor: str, backup_id: str | None) -> None:
        log = data_dir() / "config-audit.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": _now(), "file": name, "actor": actor, "backup": backup_id}
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def audit_log(self, limit: int = 50) -> list[dict]:
        log = data_dir() / "config-audit.jsonl"
        if not log.is_file():
            return []
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))
