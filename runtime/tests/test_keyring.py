from yozhan_runtime.providers.keyring import KeyRing


def test_reads_only_configured_and_present_env_vars(monkeypatch):
    monkeypatch.setenv("K1", "value1")
    monkeypatch.delenv("K2", raising=False)
    ring = KeyRing("test", [{"env": "K1"}, {"env": "K2"}])
    assert len(ring) == 1
    assert ring.current() == "value1"


def test_empty_keyring_is_falsy_and_zero_length():
    ring = KeyRing("test", [])
    assert not ring
    assert len(ring) == 0


def test_rotate_cycles_through_keys_and_wraps(monkeypatch):
    monkeypatch.setenv("K1", "value1")
    monkeypatch.setenv("K2", "value2")
    ring = KeyRing("test", [{"env": "K1"}, {"env": "K2"}])

    assert ring.current() == "value1"
    ring.rotate()
    assert ring.current() == "value2"
    ring.rotate()
    assert ring.current() == "value1"
