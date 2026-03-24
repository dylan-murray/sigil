from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sigil.pipeline.discovery import (
    _should_skip,
    _summarize_source_files,
    discover,
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

    assert "README" in result
    assert "CLAUDE.md" not in result
    assert "Use pytest" not in result


async def test_discover_git_failure(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project")
    (tmp_path / ".git").mkdir()

    async def failing_arun(cmd, **kwargs):
        return (1, "", "fatal: not a git repository")

    with patch("sigil.pipeline.discovery.arun", new_callable=AsyncMock, side_effect=failing_arun):
        result = await discover(tmp_path, "gpt-4o")

    assert "File count: 0" in result
    assert "(no commits)" in result
    assert "# Project" in result


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
