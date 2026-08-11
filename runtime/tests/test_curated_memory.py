import pytest

from yozhan_runtime.memory.curated import MEMORY_CAP_CHARS, CuratedMemory, MemoryCapExceeded


def test_starts_empty(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    assert memory.read("memory") == ""
    assert memory.as_system_prompt() is None


def test_add_and_read_back(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    memory.add("prefers dark mode")
    assert "- prefers dark mode" in memory.read("memory")


def test_add_is_deduplicated(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    memory.add("prefers dark mode")
    memory.add("prefers dark mode")
    assert memory.read("memory").count("prefers dark mode") == 1


def test_remove_drops_matching_notes(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    memory.add("prefers dark mode")
    memory.add("works in UTC+1")
    memory.remove("dark mode")
    contents = memory.read("memory")
    assert "dark mode" not in contents
    assert "UTC+1" in contents


def test_memory_and_user_files_are_separate(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    memory.add("a project fact", kind="memory")
    memory.add("is a backend engineer", kind="user")
    assert "project fact" in memory.read("memory")
    assert "project fact" not in memory.read("user")
    assert "backend engineer" in memory.read("user")


def test_writing_over_the_cap_is_refused(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    with pytest.raises(MemoryCapExceeded):
        memory.write("x" * (MEMORY_CAP_CHARS + 1), kind="memory")


def test_persists_across_instances(tmp_path):
    CuratedMemory(base_dir=tmp_path).add("durable note")
    assert "durable note" in CuratedMemory(base_dir=tmp_path).read("memory")


def test_system_prompt_includes_both_files(tmp_path):
    memory = CuratedMemory(base_dir=tmp_path)
    memory.add("deploys on Fridays", kind="memory")
    memory.add("named Sam", kind="user")
    prompt = memory.as_system_prompt()
    assert "deploys on Fridays" in prompt
    assert "named Sam" in prompt


def test_unknown_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        CuratedMemory(base_dir=tmp_path).read("nonsense")
