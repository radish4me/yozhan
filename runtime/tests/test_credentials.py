"""Credential vault. The tests that matter are the refusals: a password must
never come back out through an API, and a credential must never be usable on a
site it wasn't stored for — that binding is what stops a prompt-injected page
from talking the agent into handing credentials to an attacker.
"""

import json

import pytest

from yozhan_runtime.credentials import CredentialError, CredentialVault, normalise_host


def vault(tmp_path) -> CredentialVault:
    return CredentialVault(path=tmp_path / "creds.enc", key_path=tmp_path / "creds.key")


# --- host normalisation -----------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("github.com", "github.com"),
        ("https://github.com/login", "github.com"),
        ("HTTPS://GitHub.com/", "github.com"),
        ("www.github.com", "github.com"),
        ("github.com:443", "github.com"),
    ],
)
def test_hosts_normalise(value, expected):
    assert normalise_host(value) == expected


@pytest.mark.parametrize("value", ["", "localhost", "not a host"])
def test_bad_hosts_rejected(value):
    with pytest.raises(CredentialError):
        normalise_host(value)


# --- storage ----------------------------------------------------------------


def test_store_and_resolve(tmp_path):
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    assert v.resolve("github", "https://github.com/login") == ("radha", "hunter2hunter2")


def test_the_password_is_not_readable_on_disk(tmp_path):
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    on_disk = (tmp_path / "creds.enc").read_text(encoding="utf-8")
    assert "hunter2hunter2" not in on_disk


def test_listing_never_exposes_passwords(tmp_path):
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    dumped = json.dumps([c.__dict__ for c in v.list()])
    assert "hunter2hunter2" not in dumped
    assert "radha" in dumped and "github.com" in dumped


def test_credentials_persist_across_instances(tmp_path):
    vault(tmp_path).store("github", "github.com", "radha", "hunter2hunter2")
    reopened = CredentialVault(path=tmp_path / "creds.enc", key_path=tmp_path / "creds.key")
    assert reopened.resolve("github", "https://github.com")[0] == "radha"


def test_delete_removes_it(tmp_path):
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    v.delete("github")
    assert v.list() == []
    with pytest.raises(CredentialError):
        v.delete("github")


def test_empty_username_or_password_rejected(tmp_path):
    v = vault(tmp_path)
    with pytest.raises(CredentialError):
        v.store("x", "example.com", "", "password")
    with pytest.raises(CredentialError):
        v.store("x", "example.com", "user", "")


def test_bad_names_rejected(tmp_path):
    v = vault(tmp_path)
    for name in ["has space", "../escape", "a/b"]:
        with pytest.raises(CredentialError):
            v.store(name, "example.com", "u", "p")


# --- domain binding ---------------------------------------------------------


def test_a_credential_is_refused_on_another_domain(tmp_path):
    # The core guard: a page yozhan reads may try to talk the agent into
    # signing in somewhere else.
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    with pytest.raises(CredentialError, match="bound to github.com"):
        v.resolve("github", "https://evil-github-login.com/signin")


def test_a_lookalike_domain_is_refused(tmp_path):
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    for attacker in ["https://github.com.evil.com/", "https://notgithub.com/", "https://github.co/"]:
        with pytest.raises(CredentialError):
            v.resolve("github", attacker)


def test_subdomains_of_the_stored_host_are_allowed(tmp_path):
    # accounts.google.com for a credential stored against google.com is the
    # ordinary case, not an attack.
    v = vault(tmp_path)
    v.store("google", "google.com", "radha", "hunter2hunter2")
    assert v.resolve("google", "https://accounts.google.com/signin")[0] == "radha"


def test_unknown_credential_name_lists_what_exists(tmp_path):
    v = vault(tmp_path)
    v.store("github", "github.com", "radha", "hunter2hunter2")
    with pytest.raises(CredentialError, match="github"):
        v.resolve("gitlab", "https://gitlab.com")


def test_a_different_key_cannot_decrypt(tmp_path):
    # Confirms the stored value really is encrypted, not merely encoded.
    vault(tmp_path).store("github", "github.com", "radha", "hunter2hunter2")
    from cryptography.fernet import Fernet

    (tmp_path / "other.key").write_bytes(Fernet.generate_key())
    other = CredentialVault(path=tmp_path / "creds.enc", key_path=tmp_path / "other.key")
    with pytest.raises(Exception):
        other.resolve("github", "https://github.com")
