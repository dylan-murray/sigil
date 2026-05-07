from pathlib import Path

from sigil.pipeline.calibration import (
    _adjust_risk,
    _extract_symbol_at_line,
    _extract_symbols_from_file,
    _find_test_files,
    _has_test_coverage,
    calibrate_findings,
)
from sigil.pipeline.models import Finding


def _finding(**overrides) -> Finding:
    defaults = dict(
        category="dead_code",
        file="src/foo.py",
        line=5,
        description="Unused import",
        risk="medium",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Easy fix",
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _write_py(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_extract_symbol_at_line_function():
    lines = [
        "class Foo:",
        "    def bar(self):",
        "        pass",
        "    def baz(self):",
        "        pass",
    ]
    assert _extract_symbol_at_line(lines, 4) == "baz"


def test_extract_symbol_at_line_class():
    lines = [
        "class Foo:",
        "    x = 1",
        "    def bar(self):",
        "        pass",
    ]
    assert _extract_symbol_at_line(lines, 2) == "Foo"


def test_extract_symbol_at_line_top_level_function():
    lines = [
        "def top_level():",
        "    pass",
        "",
        "def other():",
        "    pass",
    ]
    assert _extract_symbol_at_line(lines, 3) == "top_level"


def test_extract_symbol_at_line_async_function():
    lines = [
        "async def fetch_data():",
        "    pass",
        "",
        "x = 1",
    ]
    assert _extract_symbol_at_line(lines, 4) == "fetch_data"


def test_extract_symbol_at_line_out_of_range():
    assert _extract_symbol_at_line(["pass"], 0) is None
    assert _extract_symbol_at_line(["pass"], 5) is None


def test_extract_symbol_at_line_empty():
    assert _extract_symbol_at_line([], 1) is None


def test_extract_symbols_from_file(tmp_path):
    src = tmp_path / "mod.py"
    _write_py(src, "def foo():\n    pass\n\nclass Bar:\n    pass\n")
    symbols = _extract_symbols_from_file(tmp_path, "mod.py")
    assert "foo" in symbols
    assert "Bar" in symbols


def test_extract_symbols_from_file_missing(tmp_path):
    assert _extract_symbols_from_file(tmp_path, "nonexistent.py") == []


def test_extract_symbols_from_file_unreadable(tmp_path):
    src = tmp_path / "mod.py"
    _write_py(src, "def foo():\n    pass\n")
    src.chmod(0o000)
    try:
        result = _extract_symbols_from_file(tmp_path, "mod.py")
        assert result == []
    finally:
        src.chmod(0o644)


def test_find_test_files(tmp_path):
    tests = tmp_path / "tests"
    _write_py(tests / "test_foo.py", "pass")
    _write_py(tests / "test_bar.py", "pass")
    _write_py(tests / "sub" / "test_baz.py", "pass")
    _write_py(tests / "helper.py", "pass")

    found = _find_test_files(tmp_path, "tests")
    names = [p.name for p in found]
    assert "test_foo.py" in names
    assert "test_bar.py" in names
    assert "test_baz.py" in names
    assert "helper.py" not in names


def test_find_test_files_missing_dir(tmp_path):
    assert _find_test_files(tmp_path, "tests") == []


def test_has_test_coverage_by_filename():
    repo = Path("/tmp/fake")
    test_files = [Path("/tmp/fake/tests/test_config.py")]
    assert _has_test_coverage(repo, [], "src/config.py", test_files) is True


def test_has_test_coverage_by_symbol():
    repo = Path("/tmp/fake")
    tf = Path("/tmp/fake/tests/test_foo.py")
    test_files = [tf]
    assert _has_test_coverage(repo, ["my_func"], "src/foo.py", test_files) is True


def test_has_test_coverage_no_match():
    repo = Path("/tmp/fake")
    test_files = [Path("/tmp/fake/tests/test_other.py")]
    assert _has_test_coverage(repo, ["my_func"], "src/foo.py", test_files) is False


def test_has_test_coverage_suffix_match():
    repo = Path("/tmp/fake")
    test_files = [Path("/tmp/fake/tests/foo_test.py")]
    assert _has_test_coverage(repo, [], "src/foo.py", test_files) is True


def test_adjust_risk_covered():
    assert _adjust_risk("low", True) == "medium"
    assert _adjust_risk("medium", True) == "high"
    assert _adjust_risk("high", True) == "high"


def test_adjust_risk_uncovered():
    assert _adjust_risk("high", False) == "medium"
    assert _adjust_risk("medium", False) == "low"
    assert _adjust_risk("low", False) == "low"


def test_adjust_risk_unknown():
    assert _adjust_risk("critical", True) == "high"
    assert _adjust_risk("critical", False) == "low"


def test_calibrate_findings_empty():
    assert calibrate_findings([], Path("/tmp/fake")) == []


def test_calibrate_findings_covered_elevates_risk(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "foo.py", "def my_func():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_foo.py", "from src.foo import my_func\n")

    finding = _finding(file="src/foo.py", line=1, risk="low")
    result = calibrate_findings([finding], tmp_path)

    assert len(result) == 1
    assert result[0].risk == "medium"
    assert "coverage:" in result[0].rationale
    assert "my_func" in result[0].rationale


def test_calibrate_findings_uncovered_lowers_risk(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "bar.py", "def my_func():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_other.py", "pass\n")

    finding = _finding(file="src/bar.py", line=1, risk="high")
    result = calibrate_findings([finding], tmp_path)

    assert len(result) == 1
    assert result[0].risk == "medium"
    assert "no tests found" in result[0].rationale


def test_calibrate_findings_high_stays_high_when_covered(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "foo.py", "def my_func():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_foo.py", "from src.foo import my_func\n")

    finding = _finding(file="src/foo.py", line=1, risk="high")
    result = calibrate_findings([finding], tmp_path)

    assert result[0].risk == "high"


def test_calibrate_findings_low_stays_low_when_uncovered(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "bar.py", "def my_func():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_other.py", "pass\n")

    finding = _finding(file="src/bar.py", line=1, risk="low")
    result = calibrate_findings([finding], tmp_path)

    assert result[0].risk == "low"


def test_calibrate_findings_no_line_number(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "baz.py", "def func_a():\n    pass\n\ndef func_b():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_baz.py", "from src.baz import func_a\n")

    finding = _finding(file="src/baz.py", line=None, risk="low")
    result = calibrate_findings([finding], tmp_path)

    assert result[0].risk == "medium"
    assert "coverage:" in result[0].rationale


def test_calibrate_findings_file_not_found(tmp_path):
    finding = _finding(file="src/nonexistent.py", line=5, risk="medium")
    result = calibrate_findings([finding], tmp_path)

    assert len(result) == 1
    assert result[0].risk == "medium"
    assert result[0].rationale == "Easy fix"


def test_calibrate_findings_preserves_other_fields(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "foo.py", "def my_func():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_foo.py", "from src.foo import my_func\n")

    finding = _finding(
        file="src/foo.py",
        line=1,
        risk="low",
        category="security",
        description="SQL injection",
        suggested_fix="Parameterize",
        disposition="issue",
        priority=5,
        rationale="Critical issue",
    )
    result = calibrate_findings([finding], tmp_path)

    assert result[0].category == "security"
    assert result[0].description == "SQL injection"
    assert result[0].suggested_fix == "Parameterize"
    assert result[0].disposition == "issue"
    assert result[0].priority == 5


def test_calibrate_findings_filename_match_without_symbol(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "config.py", "x = 1\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_config.py", "pass\n")

    finding = _finding(file="src/config.py", line=1, risk="low")
    result = calibrate_findings([finding], tmp_path)

    assert result[0].risk == "medium"
    assert "coverage:" in result[0].rationale


def test_calibrate_findings_multiple_findings(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "covered.py", "def my_func():\n    pass\n")
    _write_py(src / "uncovered.py", "def other_func():\n    pass\n")
    tests = tmp_path / "tests"
    _write_py(tests / "test_covered.py", "from src.covered import my_func\n")

    f1 = _finding(file="src/covered.py", line=1, risk="low")
    f2 = _finding(file="src/uncovered.py", line=1, risk="high")

    result = calibrate_findings([f1, f2], tmp_path)

    assert result[0].risk == "medium"
    assert result[1].risk == "medium"


def test_calibrate_findings_unreadable_source(tmp_path):
    src = tmp_path / "src"
    f = src / "secret.py"
    _write_py(f, "def my_func():\n    pass\n")
    f.chmod(0o000)
    try:
        finding = _finding(file="src/secret.py", line=1, risk="medium")
        result = calibrate_findings([finding], tmp_path)
        assert len(result) == 1
        assert result[0].risk == "medium"
    finally:
        f.chmod(0o644)


def test_calibrate_findings_custom_test_dir(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "foo.py", "def my_func():\n    pass\n")
    custom_tests = tmp_path / "custom_tests"
    _write_py(custom_tests / "test_foo.py", "from src.foo import my_func\n")

    finding = _finding(file="src/foo.py", line=1, risk="low")
    result = calibrate_findings([finding], tmp_path, test_dir="custom_tests")

    assert result[0].risk == "medium"


def test_calibrate_findings_no_test_dir(tmp_path):
    src = tmp_path / "src"
    _write_py(src / "foo.py", "def my_func():\n    pass\n")

    finding = _finding(file="src/foo.py", line=1, risk="medium")
    result = calibrate_findings([finding], tmp_path)

    assert result[0].risk == "low"
    assert "no tests found" in result[0].rationale
