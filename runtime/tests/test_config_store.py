"""Config read/write. The validation tests carry the weight: a saved config
that doesn't resolve breaks every task, and recovering means shell access.
"""

import pytest
import yaml

from yozhan_runtime.config_store import ConfigStore, ConfigValidationError, validate_pair

PROVIDERS = {
    "providers": {
        "local": {
            "type": "llama_cpp",
            "base_url": "http://llama-server:8080/v1",
            "models": [{"id": "qwen3.5-0.8b"}],
            "default_model": "qwen3.5-0.8b",
        },
        "gemini": {"type": "gemini", "api_keys": [{"env": "GEMINI_API_KEY_1"}], "models": ["gemini-2.5-flash"]},
    },
    "fallback_chains": {
        "default": [{"provider": "gemini", "model": "gemini-2.5-flash"}, {"provider": "local", "model": "qwen3.5-0.8b"}],
        "local_first": [{"provider": "local", "model": "qwen3.5-0.8b"}],
    },
}

AGENTS = {
    "defaults": {"fallback_chain": "default", "sandbox": "non-privileged-only"},
    "agents": {
        "orchestrator": {"fallback_chain": "default", "mode": "on-demand"},
        "researcher": {"fallback_chain": "local_first", "mode": "on-demand"},
    },
}


def make_store(tmp_path) -> ConfigStore:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "providers.yaml").write_text(yaml.safe_dump(PROVIDERS), encoding="utf-8")
    (config_dir / "agents.yaml").write_text(yaml.safe_dump(AGENTS), encoding="utf-8")
    return ConfigStore(directory=config_dir, backup_dir=tmp_path / "backups")


# --- validation -------------------------------------------------------------


def test_a_valid_pair_passes():
    validate_pair(AGENTS, PROVIDERS)


def test_agent_referencing_a_missing_chain_is_rejected():
    bad = {"defaults": {}, "agents": {"x": {"fallback_chain": "local_frist"}}}  # typo
    with pytest.raises(ConfigValidationError, match="local_frist"):
        validate_pair(bad, PROVIDERS)


def test_chain_referencing_a_missing_provider_is_rejected():
    bad = {**PROVIDERS, "fallback_chains": {"default": [{"provider": "openai", "model": "gpt-5.1"}]}}
    with pytest.raises(ConfigValidationError, match="unknown provider 'openai'"):
        validate_pair(AGENTS, bad)


def test_agent_pinned_to_a_missing_provider_is_rejected():
    bad = {"defaults": {}, "agents": {"x": {"provider": "anthropic", "model": "claude-sonnet-5"}}}
    with pytest.raises(ConfigValidationError, match="unknown provider"):
        validate_pair(bad, PROVIDERS)


def test_provider_without_a_type_is_rejected():
    bad = {"providers": {"local": {"models": ["m"]}}, "fallback_chains": {}}
    with pytest.raises(ConfigValidationError, match="missing `type:`"):
        validate_pair({"agents": {"a": {}}, "defaults": {}}, bad)


def test_empty_config_is_rejected():
    with pytest.raises(ConfigValidationError, match="at least one provider"):
        validate_pair(AGENTS, {"providers": {}})
    with pytest.raises(ConfigValidationError, match="at least one agent"):
        validate_pair({"agents": {}}, PROVIDERS)


def test_empty_chain_is_rejected():
    bad = {**PROVIDERS, "fallback_chains": {"default": []}}
    with pytest.raises(ConfigValidationError, match="is empty"):
        validate_pair(AGENTS, bad)


def test_invalid_sandbox_mode_is_rejected():
    bad = {**AGENTS, "defaults": {"fallback_chain": "default", "sandbox": "kind-of"}}
    with pytest.raises(ConfigValidationError, match="defaults.sandbox"):
        validate_pair(bad, PROVIDERS)


# --- reading ----------------------------------------------------------------


def test_reads_raw_and_parsed(tmp_path):
    store = make_store(tmp_path)
    assert "providers:" in store.raw("providers.yaml")
    assert "local" in store.providers()["providers"]


def test_unknown_file_is_refused(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="unknown config file"):
        store.raw("../../etc/passwd")


def test_edits_on_disk_are_picked_up_without_a_restart(tmp_path):
    store = make_store(tmp_path)
    assert "extra" not in store.agents()["agents"]

    updated = {**AGENTS, "agents": {**AGENTS["agents"], "extra": {"fallback_chain": "default"}}}
    path = store.path("agents.yaml")
    path.write_text(yaml.safe_dump(updated), encoding="utf-8")
    # mtime resolution can be coarse; force a distinct value.
    import os, time

    os.utime(path, (time.time() + 1, time.time() + 1))

    assert "extra" in store.agents()["agents"]


# --- writing ----------------------------------------------------------------


def test_writing_valid_config_persists_it(tmp_path):
    store = make_store(tmp_path)
    updated = {**AGENTS, "agents": {**AGENTS["agents"], "coder": {"fallback_chain": "local_first"}}}

    store.write("agents.yaml", yaml.safe_dump(updated), actor="radha")

    assert "coder" in store.agents()["agents"]
    assert "coder" in store.raw("agents.yaml")


def test_writing_invalid_config_is_refused_and_changes_nothing(tmp_path):
    store = make_store(tmp_path)
    before = store.raw("agents.yaml")

    bad = yaml.safe_dump({"defaults": {}, "agents": {"x": {"fallback_chain": "nope"}}})
    with pytest.raises(ConfigValidationError):
        store.write("agents.yaml", bad)

    assert store.raw("agents.yaml") == before


def test_writing_malformed_yaml_is_refused(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ConfigValidationError, match="invalid YAML"):
        store.write("agents.yaml", "agents: [unclosed")


def test_deleting_a_provider_an_agent_needs_is_refused(tmp_path):
    # The cross-file check: providers.yaml is validated against the agents that
    # actually exist, not on its own.
    store = make_store(tmp_path)
    without_local = {
        "providers": {k: v for k, v in PROVIDERS["providers"].items() if k != "local"},
        "fallback_chains": {"default": [{"provider": "gemini", "model": "gemini-2.5-flash"}]},
    }
    with pytest.raises(ConfigValidationError):
        store.write("providers.yaml", yaml.safe_dump(without_local))


def test_validate_candidate_does_not_write(tmp_path):
    store = make_store(tmp_path)
    before = store.raw("agents.yaml")
    updated = {**AGENTS, "agents": {**AGENTS["agents"], "coder": {"fallback_chain": "local_first"}}}
    store.validate_candidate("agents.yaml", yaml.safe_dump(updated))
    assert store.raw("agents.yaml") == before


# --- backups ----------------------------------------------------------------


def test_a_write_creates_a_restorable_backup(tmp_path):
    store = make_store(tmp_path)
    original = store.raw("agents.yaml")

    updated = {**AGENTS, "agents": {**AGENTS["agents"], "coder": {"fallback_chain": "local_first"}}}
    store.write("agents.yaml", yaml.safe_dump(updated))

    backups = store.list_backups("agents.yaml")
    assert len(backups) == 1
    assert store.read_backup(backups[0].id) == original


def test_restore_brings_back_the_previous_version(tmp_path):
    store = make_store(tmp_path)
    updated = {**AGENTS, "agents": {**AGENTS["agents"], "coder": {"fallback_chain": "local_first"}}}
    store.write("agents.yaml", yaml.safe_dump(updated))
    assert "coder" in store.agents()["agents"]

    store.restore(store.list_backups("agents.yaml")[0].id)

    assert "coder" not in store.agents()["agents"]


def test_backup_ids_cannot_escape_the_backup_directory(tmp_path):
    store = make_store(tmp_path)
    for attempt in ["../../../etc/passwd", "..", "nope"]:
        with pytest.raises(ValueError, match="no such backup"):
            store.read_backup(attempt)


def test_audit_log_records_who_changed_what(tmp_path, monkeypatch):
    monkeypatch.setenv("YOZHAN_DATA_DIR", str(tmp_path / "data"))
    store = make_store(tmp_path)
    updated = {**AGENTS, "agents": {**AGENTS["agents"], "coder": {"fallback_chain": "local_first"}}}
    store.write("agents.yaml", yaml.safe_dump(updated), actor="radha")

    entries = store.audit_log()
    assert entries[0]["actor"] == "radha"
    assert entries[0]["file"] == "agents.yaml"
