from pathlib import Path

from sigil.core.instructions import (
    MAX_TOTAL_CHARS,
    PER_FILE_MAX_CHARS,
    Instructions,
    detect_instructions,
)


def test_detect_no_configs(tmp_path: Path) -> None:
    result = detect_instructions(tmp_path)
    assert not result.has_instructions
    assert result.content == ""
    assert result.detected_files == ()


def test_agents_md_wins_over_claude_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents rules")
    (tmp_path / "CLAUDE.md").write_text("claude rules")
    result = detect_instructions(tmp_path)
    assert result.detected_files == ("AGENTS.md",)
    assert result.content == "agents rules"
    assert "claude" not in result.content


def test_fallback_to_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude rules")
    result = detect_instructions(tmp_path)
    assert result.detected_files == ("CLAUDE.md",)
    assert result.source == "Claude Code"


def test_fallback_to_cursorrules(tmp_path: Path) -> None:
    (tmp_path / ".cursorrules").write_text("cursor rules")
    result = detect_instructions(tmp_path)
    assert result.detected_files == (".cursorrules",)


def test_copilot_instructions(tmp_path: Path) -> None:
    gh_dir = tmp_path / ".github"
    gh_dir.mkdir()
    (gh_dir / "copilot-instructions.md").write_text("copilot rules")
    result = detect_instructions(tmp_path)
    assert result.detected_files == (".github/copilot-instructions.md",)
    assert result.source == "GitHub Copilot"


def test_codex_md(tmp_path: Path) -> None:
    (tmp_path / "codex.md").write_text("codex rules")
    result = detect_instructions(tmp_path)
    assert result.detected_files == ("codex.md",)
    assert result.source == "Codex (OpenAI)"


def test_cursor_rules_dir(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "style.md").write_text("use tabs")
    (rules_dir / "naming.mdc").write_text("PascalCase")
    (rules_dir / "ignored.json").write_text("{}")

    result = detect_instructions(tmp_path)
    assert result.has_instructions
    assert ".cursor/rules/style.md" in result.detected_files
    assert ".cursor/rules/naming.mdc" in result.detected_files
    assert len(result.detected_files) == 2
    assert "use tabs" in result.content
    assert "PascalCase" in result.content


def test_agents_md_beats_cursor_dir(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents wins")
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "style.md").write_text("cursor rules")

    result = detect_instructions(tmp_path)
    assert result.detected_files == ("AGENTS.md",)
    assert "cursor" not in result.content


def test_cursor_dir_beats_cursorrules(tmp_path: Path) -> None:
    (tmp_path / ".cursorrules").write_text("legacy rules")
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "style.md").write_text("current rules")

    result = detect_instructions(tmp_path)
    assert ".cursor/rules/style.md" in result.detected_files
    assert "current rules" in result.content
    assert "legacy" not in result.content


def test_per_file_truncation(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x" * (MAX_TOTAL_CHARS + 500))
    result = detect_instructions(tmp_path)
    assert result.content.endswith("... (truncated)")
    assert len(result.content) <= MAX_TOTAL_CHARS + 20


def test_cursor_dir_respects_total_budget(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "a.md").write_text("a" * PER_FILE_MAX_CHARS)
    (rules_dir / "b.md").write_text("b" * PER_FILE_MAX_CHARS)
    (rules_dir / "c.md").write_text("c" * PER_FILE_MAX_CHARS)

    result = detect_instructions(tmp_path)
    assert len(result.content) <= MAX_TOTAL_CHARS + len("\n\n") * 2 + 20


def test_cursor_dir_skips_files_beyond_budget(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "a.md").write_text("a" * PER_FILE_MAX_CHARS)
    (rules_dir / "b.md").write_text("b" * PER_FILE_MAX_CHARS)
    (rules_dir / "c.md").write_text("c" * PER_FILE_MAX_CHARS)

    result = detect_instructions(tmp_path)
    assert ".cursor/rules/a.md" in result.detected_files
    assert ".cursor/rules/b.md" in result.detected_files
    assert ".cursor/rules/c.md" not in result.detected_files


def test_no_double_truncation(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x" * (MAX_TOTAL_CHARS + 1000))
    result = detect_instructions(tmp_path)
    assert result.content.count("... (truncated)") == 1


def test_format_for_prompt() -> None:
    result = Instructions(detected_files=("AGENTS.md",), source="Codex", content="rule one")
    prompt = result.format_for_prompt()
    assert "`AGENTS.md`" in prompt
    assert "rule one" in prompt


def test_format_for_pr_body() -> None:
    result = Instructions(detected_files=("AGENTS.md",), source="Codex", content="x")
    body = result.format_for_pr_body()
    assert "## Repo Conventions" in body
    assert "`AGENTS.md`" in body


def test_empty_file_skipped(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("")
    (tmp_path / "CLAUDE.md").write_text("claude rules")
    result = detect_instructions(tmp_path)
    assert result.detected_files == ("CLAUDE.md",)


def test_unreadable_file_skipped(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("content")
    agents.chmod(0o000)
    (tmp_path / "CLAUDE.md").write_text("fallback")
    try:
        result = detect_instructions(tmp_path)
        assert result.detected_files == ("CLAUDE.md",)
    finally:
        agents.chmod(0o644)
