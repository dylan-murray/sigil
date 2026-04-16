from pathlib import Path
from sigil.pipeline.errors import find_poor_errors


def test_find_poor_errors_happy_path(tmp_path: Path):
    code = """
def good_func():
    try:
        do_something()
    except ValueError as e:
        raise RuntimeError(f"Failed to process data: {e}")
    """
    file = tmp_path / "good.py"
    file.write_text(code)

    findings = find_poor_errors(tmp_path)
    assert len(findings) == 0


def test_find_poor_errors_vague_message(tmp_path: Path):
    code = 'raise Exception("error")'
    file = tmp_path / "vague.py"
    file.write_text(code)

    findings = find_poor_errors(tmp_path)
    assert len(findings) == 1
    assert "Vague error message: 'error'" in findings[0].description


def test_find_poor_errors_short_message(tmp_path: Path):
    code = 'raise Exception("too short")'
    file = tmp_path / "short.py"
    file.write_text(code)

    findings = find_poor_errors(tmp_path)
    assert len(findings) == 1
    assert "Vague error message: 'too short'" in findings[0].description


def test_find_poor_errors_bare_exception_raise(tmp_path: Path):
    code = "raise ValueError"
    file = tmp_path / "bare_raise.py"
    file.write_text(code)

    findings = find_poor_errors(tmp_path)
    assert len(findings) == 1
    assert "Exception raised without a message" in findings[0].description


def test_find_poor_errors_bare_except(tmp_path: Path):
    code = """
try:
    do_something()
except:
    pass
    """
    file = tmp_path / "bare_except.py"
    file.write_text(code)

    findings = find_poor_errors(tmp_path)
    assert len(findings) == 1
    assert "Bare 'except:' block detected" in findings[0].description


def test_find_poor_errors_re_raise(tmp_path: Path):
    code = """
try:
    do_something()
except Exception:
    raise
    """
    file = tmp_path / "re_raise.py"
    file.write_text(code)

    findings = find_poor_errors(tmp_path)
    assert len(findings) == 0


def test_find_poor_errors_syntax_error(tmp_path: Path):
    code = "this is not valid python"
    file = tmp_path / "invalid.py"
    file.write_text(code)

    # Should not crash
    findings = find_poor_errors(tmp_path)
    assert len(findings) == 0
