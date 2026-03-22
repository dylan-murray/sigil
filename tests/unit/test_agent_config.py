from pathlib import Path

from sigil.agent_config import MAX_CONFIG_CHARS, AgentConfigResult, detect_agent_config


def test_detect_no_configs(tmp_path: Path) -> None:
    result = detect_agent_config(tmp_path)
    assert not result.has_config
    assert result.content == ""
    assert result.detected_files == []


def test_detect_agents_md_first(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents rules")
    (tmp_path / "CLAUDE.md").write_text("claude rules")
    result = detect_agent_config(tmp_path)
    assert result.has_config
    assert result.detected_files == ["AGENTS.md"]
    assert result.content == "agents rules"
    assert "CLAUDE.md" not in result.content


def test_fallback_to_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude rules")
    result = detect_agent_config(tmp_path)
    assert result.detected_files == ["CLAUDE.md"]
    assert result.source == "Claude Code"


def test_fallback_to_cursorrules(tmp_path: Path) -> None:
    (tmp_path / ".cursorrules").write_text("cursor rules")
    result = detect_agent_config(tmp_path)
    assert result.detected_files == [".cursorrules"]


def test_fallback_to_cursor_rules_dir(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "style.md").write_text("use tabs")
    (rules_dir / "naming.mdc").write_text("PascalCase")
    (rules_dir / "ignored.json").write_text("{}")

    result = detect_agent_config(tmp_path)
    assert result.has_config
    assert ".cursor/rules/style.md" in result.detected_files
    assert ".cursor/rules/naming.mdc" in result.detected_files
    assert len(result.detected_files) == 2
    assert "use tabs" in result.content
    assert "PascalCase" in result.content


def test_single_file_beats_cursor_dir(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents wins")
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "style.md").write_text("cursor rules")

    result = detect_agent_config(tmp_path)
    assert result.detected_files == ["AGENTS.md"]


def test_truncation(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x" * (MAX_CONFIG_CHARS + 500))
    result = detect_agent_config(tmp_path)
    assert len(result.content) < MAX_CONFIG_CHARS + 100
    assert result.content.endswith("... (truncated)")


def test_format_for_prompt() -> None:
    result = AgentConfigResult(detected_files=["AGENTS.md"], source="Codex", content="rule one")
    prompt = result.format_for_prompt()
    assert "`AGENTS.md`" in prompt
    assert "rule one" in prompt


def test_format_for_pr_body() -> None:
    result = AgentConfigResult(detected_files=["AGENTS.md"], source="Codex", content="x")
    body = result.format_for_pr_body()
    assert "## Repo Conventions" in body
    assert "`AGENTS.md`" in body


def test_empty_file_skipped(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("")
    (tmp_path / "CLAUDE.md").write_text("claude rules")
    result = detect_agent_config(tmp_path)
    assert result.detected_files == ["CLAUDE.md"]


def test_unreadable_file_skipped(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("content")
    agents.chmod(0o000)
    (tmp_path / "CLAUDE.md").write_text("fallback")
    try:
        result = detect_agent_config(tmp_path)
        assert result.detected_files == ["CLAUDE.md"]
    finally:
        agents.chmod(0o644)
