from pathlib import Path

from yozhan_runtime.skills.manager import SkillManager

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def test_discovers_all_built_in_skills():
    manager = SkillManager([REPO_SKILLS_DIR])
    skills = manager.discover()
    names = {s.name for s in skills}
    assert names == {"example-echo", "read-file", "web-search", "memory-note", "a2a-peer"}


def test_instruction_only_skill_has_no_tool():
    manager = SkillManager([REPO_SKILLS_DIR])
    skills = {s.name: s for s in manager.discover()}
    assert skills["example-echo"].tool_name is None
    assert len(manager.as_openai_tools()) == 4  # read_file, web_search, memory_note, a2a_peer — echo excluded


def test_tool_skills_are_exposed_as_openai_tools():
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    tool_names = {t["function"]["name"] for t in manager.as_openai_tools()}
    assert tool_names == {"read_file", "web_search", "memory_note", "a2a_peer"}


def test_execute_web_search_stub():
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    result = manager.execute("web_search", {"query": "yozhan"})
    assert "not configured" in result
    assert "yozhan" in result


def test_execute_unknown_tool_returns_error_string():
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    result = manager.execute("does_not_exist", {})
    assert result.startswith("error:")


def test_read_file_rejects_path_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("YOZHAN_WORKSPACE_DIR", str(tmp_path / "workspace"))
    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    result = manager.execute("read_file", {"path": "../../etc/passwd"})
    assert "outside the workspace root" in result


def test_read_file_reads_a_real_file(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hello.txt").write_text("hi there", encoding="utf-8")
    monkeypatch.setenv("YOZHAN_WORKSPACE_DIR", str(workspace))

    manager = SkillManager([REPO_SKILLS_DIR])
    manager.discover()
    result = manager.execute("read_file", {"path": "hello.txt"})
    assert result == "hi there"
