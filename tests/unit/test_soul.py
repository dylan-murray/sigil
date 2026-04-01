from sigil.core.agent import Agent
from sigil.pipeline.knowledge import load_memory_files, load_soul


def test_load_soul_missing_returns_empty(tmp_path):
    assert load_soul(tmp_path) == ""


def test_load_memory_files_includes_soul(tmp_path):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "soul.md").write_text("# Soul\nKeep it small")

    result = load_memory_files(tmp_path, ["soul.md"])

    assert result[".sigil/memory/soul.md"] == "# Soul\nKeep it small"


def test_agent_system_prompt_includes_soul(tmp_path, monkeypatch):
    mdir = tmp_path / ".sigil" / "memory"
    mdir.mkdir(parents=True)
    (mdir / "soul.md").write_text("# Soul\nBe kind")
    monkeypatch.chdir(tmp_path)

    agent = Agent(label="x", model="m", tools=[], system_prompt="Base prompt")

    assert "Base prompt" in agent.system_prompt
    assert "Be kind" in agent.system_prompt
