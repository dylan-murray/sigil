from unittest.mock import patch

from sigil.pipeline.code_map import (
    _build_path_marker,
    _extract_python_functions,
    _find_callees,
    _find_test_files,
    generate_code_map,
)
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.ideation import FeatureIdea


def test_build_path_marker_shallow():
    result = _build_path_marker("config.py", "BUG: unused import")
    assert result == "config.py ← [BUG: unused import]"


def test_build_path_marker_deep():
    result = _build_path_marker("sigil/core/config.py", "BUG: unused import")
    assert result == "sigil/ → core/ → config.py ← [BUG: unused import]"


def test_build_path_marker_single_dir():
    result = _build_path_marker("src/main.py", "FEATURE: retry")
    assert result == "src/ → main.py ← [FEATURE: retry]"


def test_extract_python_functions_happy():
    code = """\
import os

def hello():
    pass

class Foo:
    def bar(self):
        pass

async def baz():
    pass
"""
    result = _extract_python_functions(code)
    assert result == ["hello", "bar", "baz"]


def test_extract_python_functions_empty():
    assert _extract_python_functions("") == []


def test_extract_python_functions_non_python():
    code = "const x = 42;\nfunction foo() { return x; }"
    assert _extract_python_functions(code) == []


def test_extract_python_functions_nested_indent():
    code = """\
def outer():
    def inner():
        pass
"""
    result = _extract_python_functions(code)
    assert "outer" in result
    assert "inner" in result


def test_find_callees_happy():
    code = """\
def process():
    data = fetch_data()
    result = transform(data)
    save(result)
    return result
"""
    result = _find_callees(code)
    assert "fetch_data" in result
    assert "transform" in result
    assert "save" in result


def test_find_callees_filters_builtins():
    code = """\
def process():
    result = len(items)
    total = sum(values)
    text = str(num)
    items = list(data)
    x = print("hi")
    data = fetch()
"""
    result = _find_callees(code)
    assert "fetch" in result
    assert "len" not in result
    assert "sum" not in result
    assert "str" not in result
    assert "list" not in result
    assert "print" not in result


def test_find_callees_filters_keywords():
    code = """\
def process():
    if check():
        for item in items:
            while running():
                pass
"""
    result = _find_callees(code)
    assert "check" in result
    assert "running" in result
    assert "if" not in result
    assert "for" not in result
    assert "while" not in result


def test_find_callees_deduplicates():
    code = """\
def process():
    fetch()
    fetch()
    fetch()
"""
    result = _find_callees(code)
    assert result.count("fetch") == 1


def test_find_callees_caps_at_five():
    code = "\n".join(f"    func_{i}()" for i in range(10))
    result = _find_callees(code)
    assert len(result) <= 5


def test_find_callees_empty():
    assert _find_callees("") == []


async def test_find_test_files_happy(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_utils.py").write_text("def test_stuff(): pass")
    (repo / "tests" / "test_other.py").write_text("def test_other(): pass")
    (repo / "src").mkdir()
    (repo / "src" / "utils.py").write_text("def helper(): pass")

    with patch("sigil.pipeline.code_map.arun") as mock_arun:
        mock_arun.return_value = (
            0,
            "tests/test_utils.py\ntests/test_other.py\nsrc/utils.py\n",
            "",
        )
        result = await _find_test_files(repo, "src/utils.py")

    assert "tests/test_utils.py" in result
    assert len(result) <= 3


async def test_find_test_files_no_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "utils.py").write_text("def helper(): pass")

    with patch("sigil.pipeline.code_map.arun") as mock_arun:
        mock_arun.return_value = (0, "src/utils.py\n", "")
        result = await _find_test_files(repo, "src/utils.py")

    assert result == []


async def test_generate_code_map_finding(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    source = repo / "src" / "utils.py"
    source.write_text("def fetch_data():\n    return query()\n\ndef save(data):\n    write(data)\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_utils.py").write_text("def test_fetch(): pass")

    finding = Finding(
        category="dead_code",
        file="src/utils.py",
        line=1,
        description="Unused function",
        risk="low",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Not referenced",
    )

    with (
        patch("sigil.pipeline.code_map.arun") as mock_arun,
        patch("sigil.pipeline.code_map._find_test_files") as mock_tests,
    ):
        mock_arun.return_value = (0, "other/caller.py\n", "")
        mock_tests.return_value = ["tests/test_utils.py"]
        result = await generate_code_map(repo, finding)

    assert "src/ → utils.py ← [DEAD_CODE: Unused function]" in result
    assert "callers:" in result
    assert "callees:" in result
    assert "tests:" in result


async def test_generate_code_map_idea(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    source = repo / "src" / "client.py"
    source.write_text("def request():\n    send()\n")

    idea = FeatureIdea(
        title="Add retry logic",
        description="Retry failed HTTP calls",
        rationale="Improves reliability",
        complexity="small",
        disposition="pr",
        priority=2,
        relevant_files=("src/client.py",),
    )

    with (
        patch("sigil.pipeline.code_map.arun") as mock_arun,
        patch("sigil.pipeline.code_map._find_test_files") as mock_tests,
    ):
        mock_arun.return_value = (0, "", "")
        mock_tests.return_value = []
        result = await generate_code_map(repo, idea)

    assert "src/ → client.py ← [Add retry logic]" in result


async def test_generate_code_map_non_python(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    source = repo / "src" / "styles.css"
    source.write_text("body { color: red; }")

    finding = Finding(
        category="bug",
        file="src/styles.css",
        line=1,
        description="Wrong color",
        risk="low",
        suggested_fix="Fix it",
        disposition="pr",
        priority=1,
        rationale="Bad style",
    )

    with patch("sigil.pipeline.code_map._find_test_files") as mock_tests:
        mock_tests.return_value = []
        result = await generate_code_map(repo, finding)

    assert "src/ → styles.css ← [BUG: Wrong color]" in result
    assert "unknown" in result


async def test_generate_code_map_missing_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    finding = Finding(
        category="dead_code",
        file="nonexistent.py",
        line=1,
        description="Gone",
        risk="low",
        suggested_fix="Remove",
        disposition="pr",
        priority=1,
        rationale="Missing",
    )

    result = await generate_code_map(repo, finding)
    assert result == ""


async def test_generate_code_map_idea_no_relevant_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    idea = FeatureIdea(
        title="Add retry logic",
        description="Retry failed HTTP calls",
        rationale="Improves reliability",
        complexity="small",
        disposition="pr",
        priority=2,
        relevant_files=(),
    )

    result = await generate_code_map(repo, idea)
    assert result == ""
