from pathlib import Path
from sigil.pipeline.types import analyze_type_coverage


def create_test_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_analyze_type_coverage_perfect(tmp_path: Path):
    code = """
def foo(a: int, b: str) -> bool:
    return True

class Bar:
    def method(self, x: float) -> None:
        pass
    """
    file_path = tmp_path / "perfect.py"
    create_test_file(file_path, code)

    report = analyze_type_coverage(tmp_path)
    assert report.coverage_percentage == 100.0
    assert len(report.missing_hints) == 0
    assert len(report.unsafe_types) == 0


def test_analyze_type_coverage_missing_return(tmp_path: Path):
    code = """
def foo(a: int) -> None:
    return None

def bar(a: int):
    return None
    """
    file_path = tmp_path / "missing_return.py"
    create_test_file(file_path, code)

    report = analyze_type_coverage(tmp_path)
    assert report.coverage_percentage == 50.0
    assert len(report.missing_hints) == 1
    assert report.missing_hints[0].function_name == "bar"
    assert report.missing_hints[0].missing_element == "return type"


def test_analyze_type_coverage_missing_args(tmp_path: Path):
    code = """
def foo(a) -> int:
    return 1

def bar(a: int) -> int:
    return 1
    """
    file_path = tmp_path / "missing_args.py"
    create_test_file(file_path, code)

    report = analyze_type_coverage(tmp_path)
    assert report.coverage_percentage == 50.0
    assert len(report.missing_hints) == 1
    assert report.missing_hints[0].function_name == "foo"
    assert report.missing_hints[0].missing_element == "argument 'a'"


def test_analyze_type_coverage_unsafe_any(tmp_path: Path):
    code = """
from typing import Any

def foo(a: Any) -> Any:
    return a
    """
    file_path = tmp_path / "unsafe_any.py"
    create_test_file(file_path, code)

    report = analyze_type_coverage(tmp_path)
    assert len(report.unsafe_types) == 2
    assert any(u.context == "argument 'a'" for u in report.unsafe_types)
    assert any(u.context == "return type" for u in report.unsafe_types)


def test_analyze_type_coverage_async_and_methods(tmp_path: Path):
    code = """
class MyClass:
    async def async_method(self, a: int) -> int:
        return a

    def method_no_return(self, a: int):
        pass
    """
    file_path = tmp_path / "mixed.py"
    create_test_file(file_path, code)

    report = analyze_type_coverage(tmp_path)
    # async_method is covered, method_no_return is missing return
    assert report.total_functions == 2
    assert report.covered_functions == 1
    assert len(report.missing_hints) == 1
    assert report.missing_hints[0].function_name == "method_no_return"


def test_analyze_type_coverage_empty_and_non_py(tmp_path: Path):
    # Empty py file
    create_test_file(tmp_path / "empty.py", "")
    # Non py file
    (tmp_path / "readme.md").write_text("# Hello")

    report = analyze_type_coverage(tmp_path)
    assert report.total_functions == 0
    assert report.coverage_percentage == 100.0
    assert len(report.missing_hints) == 0
