import pytest

from sigil.discovery import (
    _should_skip,
    _summarize_source_files,
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
