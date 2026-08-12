"""Secret storage. The tests that matter are the ones about what must NOT
happen: values leaking through the describe() API, dashboard entries silently
overriding a value set in the stack, and reserved names being writable.
"""

import json

import pytest

from yozhan_runtime.secrets import SecretError, SecretStore, validate_name


def store(tmp_path) -> SecretStore:
    return SecretStore(path=tmp_path / "secrets.json")


# --- name validation --------------------------------------------------------


def test_valid_names_accepted():
    for name in ["GEMINI_API_KEY_1", "A", "OPENAI_KEY"]:
        validate_name(name)


@pytest.mark.parametrize("name", ["lowercase", "1LEADING_DIGIT", "HAS-DASH", "HAS SPACE", "", "A" * 65])
def test_malformed_names_rejected(name):
    with pytest.raises(SecretError):
        validate_name(name)


@pytest.mark.parametrize("name", ["PATH", "YOZHAN_DATA_DIR", "GATEWAY_ADMIN_TOKEN", "LLAMA_SERVER_URL"])
def test_reserved_names_rejected(name):
    # These steer the runtime itself; setting them from the dashboard would let
    # a UI edit move where config is read from or files are written.
    with pytest.raises(SecretError, match="runtime itself"):
        validate_name(name)


# --- storage ----------------------------------------------------------------


def test_set_persists_and_reaches_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    s = store(tmp_path)
    s.set("TEST_PROVIDER_KEY", "sk-123")

    import os

    assert os.environ["TEST_PROVIDER_KEY"] == "sk-123"
    assert SecretStore(path=tmp_path / "secrets.json")._values["TEST_PROVIDER_KEY"] == "sk-123"


def test_empty_values_rejected(tmp_path):
    s = store(tmp_path)
    for value in ["", "   "]:
        with pytest.raises(SecretError, match="empty"):
            s.set("TEST_KEY", value)


def test_describe_never_returns_values(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    s = store(tmp_path)
    s.set("TEST_PROVIDER_KEY", "sk-super-secret")

    described = json.dumps(s.describe())

    assert "sk-super-secret" not in described
    entry = next(e for e in s.describe() if e["name"] == "TEST_PROVIDER_KEY")
    assert entry["stored"] is True and entry["set"] is True


def test_delete_removes_it(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    s = store(tmp_path)
    s.set("TEST_PROVIDER_KEY", "sk-123")
    s.delete("TEST_PROVIDER_KEY")

    assert not any(e["name"] == "TEST_PROVIDER_KEY" and e["stored"] for e in s.describe())
    with pytest.raises(SecretError, match="No stored secret"):
        s.delete("TEST_PROVIDER_KEY")


def test_a_value_from_the_stack_wins_over_a_stored_one(tmp_path, monkeypatch):
    # Setting a key in both places should not silently prefer the invisible
    # one — the stack is the more explicit statement of intent.
    monkeypatch.setenv("TEST_PROVIDER_KEY", "from-the-stack")
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"secrets": {"TEST_PROVIDER_KEY": "from-the-dashboard"}}), encoding="utf-8")

    SecretStore(path=path).apply_to_environment()

    import os

    assert os.environ["TEST_PROVIDER_KEY"] == "from-the-stack"


def test_apply_fills_in_an_unset_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"secrets": {"TEST_PROVIDER_KEY": "from-the-dashboard"}}), encoding="utf-8")

    SecretStore(path=path).apply_to_environment()

    import os

    assert os.environ["TEST_PROVIDER_KEY"] == "from-the-dashboard"


def test_corrupt_secrets_file_raises_rather_than_starting_empty(tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SecretError, match="not valid JSON"):
        SecretStore(path=path)
