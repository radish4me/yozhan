from yozhan_runtime.memory.store import SessionStore


def test_history_persists_across_store_instances(tmp_path):
    store = SessionStore(user_id="alice", db_dir=tmp_path)
    store.append_message("s1", "user", "hello")
    store.append_message("s1", "assistant", "hi there")
    store.close()

    reopened = SessionStore(user_id="alice", db_dir=tmp_path)
    history = reopened.get_history("s1")
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_sessions_are_isolated(tmp_path):
    store = SessionStore(user_id="bob", db_dir=tmp_path)
    store.append_message("s1", "user", "in session one")
    store.append_message("s2", "user", "in session two")
    assert store.get_history("s1") == [{"role": "user", "content": "in session one"}]
    assert store.get_history("s2") == [{"role": "user", "content": "in session two"}]


def test_full_text_search(tmp_path):
    store = SessionStore(user_id="carol", db_dir=tmp_path)
    store.append_message("s1", "user", "what is the capital of france")
    store.append_message("s1", "assistant", "Paris is the capital of France")
    store.append_message("s1", "user", "unrelated message about pizza")

    results = store.search("france")
    assert len(results) == 2
    assert all("france" in r["content"].lower() for r in results)
