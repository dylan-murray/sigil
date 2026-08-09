from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sigil.pipeline.discovery import (
    _should_skip,
    _summarize_source_files,
    discover,
    parse_gitignore,
)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("node_modules/foo/bar.js", True),
        ("src/__pycache__/mod.pyc", True),
        (".git/config", True),
        (".venv/lib/site.py", True),
        ("src/main.py", False),
        ("lib/utils.py", False),
    ],
)
def test_should_skip(path, expected):
    assert _should_skip(path) is expected


def test_summarize_source_files_budget(tmp_path):
    for i in range(10):
        (tmp_path / f"mod{i}.py").write_text(f"def func{i}():\n    pass\n")
    files = [f"mod{i}.py" for i in range(10)]
    result = _summarize_source_files(tmp_path, files, budget=100)
    assert "budget" in result.lower() or "more files" in result.lower()


def test_summarize_skips_already_read(tmp_path):
    (tmp_path / "README.md").write_text("# Hello")
    result = _summarize_source_files(tmp_path, ["README.md"], budget=10_000)
    assert result == ""


def test_summarize_includes_raw_content(tmp_path):
    (tmp_path / "app.py").write_text("def main():\n    print('hello')\n")
    result = _summarize_source_files(tmp_path, ["app.py"], budget=10_000)
    assert "def main():" in result
    assert "print('hello')" in result


async def test_discover_excludes_claude_md(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# My Project")
    (tmp_path / "CLAUDE.md").write_text("Use pytest, no comments")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"')
    (tmp_path / ".git").mkdir()

    with patch("sigil.pipeline.discovery.arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = (0, "", "")
        result = await discover(tmp_path, "gpt-4o")

    ctx = result.to_context()
    assert "README" in ctx
    assert "CLAUDE.md" not in ctx
    assert "Use pytest" not in ctx


async def test_discover_git_failure(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project")
    (tmp_path / ".git").mkdir()

    async def failing_arun(cmd, **kwargs):
        return (1, "", "fatal: not a git repository")

    with patch("sigil.pipeline.discovery.arun", new_callable=AsyncMock, side_effect=failing_arun):
        result = await discover(tmp_path, "gpt-4o")

    ctx = result.to_context()
    assert "File count: 0" in ctx
    assert "(no commits)" in ctx
    assert "# Project" in ctx


def test_summarize_unreadable_file(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("print('hello')")

    (tmp_path / "bad.py").write_text("secret")

    original_read_text = Path.read_text

    def failing_read_text(self, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("Permission denied")
        return original_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", failing_read_text):
        result = _summarize_source_files(tmp_path, ["good.py", "bad.py"], budget=10_000)

    assert "print('hello')" in result
    assert "secret" not in result


def test_parse_gitignore_missing_file(tmp_path):
    assert parse_gitignore(tmp_path) == []


def test_parse_gitignore_empty_file(tmp_path):
    (tmp_path / ".gitignore").write_text("")
    assert parse_gitignore(tmp_path) == []


def test_parse_gitignore_skips_blanks_and_comments(tmp_path):
    (tmp_path / ".gitignore").write_text("# comment\n\nnode_modules\n")
    result = parse_gitignore(tmp_path)
    assert "node_modules" in result
    assert all("# comment" not in p for p in result)


def test_parse_gitignore_skips_negation_patterns(tmp_path):
    (tmp_path / ".gitignore").write_text("!keep-me\nnode_modules\n")
    result = parse_gitignore(tmp_path)
    assert all("keep-me" not in p for p in result)
    assert "node_modules" in result


def test_parse_gitignore_simple_directory(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules\n")
    result = parse_gitignore(tmp_path)
    assert "node_modules" in result
    assert "node_modules/**" in result
    assert "*/node_modules" in result
    assert "*/node_modules/**" in result


def test_parse_gitignore_wildcard_pattern(tmp_path):
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    result = parse_gitignore(tmp_path)
    assert result == ["*.pyc"]


def test_parse_gitignore_path_relative_pattern(tmp_path):
    (tmp_path / ".gitignore").write_text("src/generated/\n")
    result = parse_gitignore(tmp_path)
    assert "src/generated" in result
    assert "src/generated/**" in result


def test_parse_gitignore_root_relative_pattern(tmp_path):
    (tmp_path / ".gitignore").write_text("/build\n")
    result = parse_gitignore(tmp_path)
    assert "build" in result
    assert "build/**" in result
    assert "*/build" in result
    assert "*/build/**" in result
    assert all(not p.startswith("/") for p in result)


def test_parse_gitignore_trailing_slash(tmp_path):
    (tmp_path / ".gitignore").write_text("dist/\n")
    result = parse_gitignore(tmp_path)
    assert "dist" in result
    assert "dist/**" in result
    assert "*/dist" in result
    assert "*/dist/**" in result


def test_parse_gitignore_deduplicates(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules\nnode_modules\n")
    result = parse_gitignore(tmp_path)
    assert result.count("node_modules") == 1


def test_parse_gitignore_unreadable_file(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules")
    with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
        result = parse_gitignore(tmp_path)
    assert result == []


async def test_discover_merges_gitignore_patterns(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project")
    (tmp_path / ".gitignore").write_text("*.pyc\nnode_modules\n")
    (tmp_path / ".git").mkdir()

    with patch("sigil.pipeline.discovery.arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = (0, "", "")
        result = await discover(tmp_path, "gpt-4o")

    assert "*.pyc" in result.ignore
    assert "node_modules" in result.ignore


async def test_discover_gitignore_additive_to_config_ignore(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project")
    (tmp_path / ".gitignore").write_text("*.log\n")
    (tmp_path / ".git").mkdir()

    with patch("sigil.pipeline.discovery.arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = (0, "", "")
        result = await discover(tmp_path, "gpt-4o", ignore=["*.secret"])

    assert "*.secret" in result.ignore
    assert "*.log" in result.ignore
    assert result.ignore.index("*.secret") < result.ignore.index("*.log")
