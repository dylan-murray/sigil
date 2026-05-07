import pytest

from sigil.core.tools import (
    MAX_READ_BYTES,
    _validate_file_syntax,
    apply_edit,
    make_apply_edit_tool,
    make_create_file_tool,
    make_multi_edit_tool,
    make_read_file_tool,
    multi_edit,
    paginate_lines,
)
from sigil.pipeline.models import FileTracker


async def test_apply_edit_handler_regression(tmp_path):
    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute({"file": "f.py", "new_content": "x"})
    assert "old_content" in result.content
    assert "Invalid arguments" in result.content


async def test_apply_edit_handler_valid_passthrough(tmp_path):
    target = tmp_path / "greet.txt"
    target.write_text("hello\nworld\n")

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "greet.txt",
            "old_content": "hello",
            "new_content": "howdy",
        }
    )

    assert "Applied edit" in result.content
    assert target.read_text() == "howdy\nworld\n"


async def test_multi_edit_handler_routes_validation_error(tmp_path):
    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute({"file": "f.py", "edits": []})
    assert "edits" in result.content
    assert "Invalid arguments" in result.content


async def test_multi_edit_changes_to_adjacent_lines(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("A\nB\nC\nD\nE\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.txt",
            "edits": [
                {"old_content": "C", "new_content": "C-modified"},
                {"old_content": "B", "new_content": "B-modified"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert target.read_text() == "A\nB-modified\nC-modified\nD\nE\n"


async def test_multi_edit_overlapping_edits_rejected(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("foo bar baz\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
            "edits": [
                {"old_content": "foo bar", "new_content": "X"},
                {"old_content": "bar baz", "new_content": "Y"},
            ],
        }
    )

    assert "Applied 0/2" in result.content
    assert "overlap" in result.content
    assert "0" in result.content and "1" in result.content
    assert target.read_text() == "foo bar baz\n"


async def test_multi_edit_reverse_order_preserves_offsets(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("line 1\nline 2\nline 3\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.txt",
            "edits": [
                {"old_content": "line 1", "new_content": "first"},
                {"old_content": "line 3", "new_content": "third updated"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert target.read_text() == "first\nline 2\nthird updated\n"


async def test_multi_edit_normalized_fallback(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("hello 'world'\nbye 'now'\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.txt",
            "edits": [
                {"old_content": "\u2018world\u2019", "new_content": "WORLD"},
                {"old_content": "\u2018now\u2019", "new_content": "NOW"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert "(normalized" in result.content
    text = target.read_text()
    assert "WORLD" in text
    assert "NOW" in text


async def test_multi_edit_partial_failure_reports_each(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("alpha\nbeta\ngamma\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.txt",
            "edits": [
                {"old_content": "alpha", "new_content": "ALPHA"},
                {"old_content": "", "new_content": "X"},
                {"old_content": "delta", "new_content": "DELTA"},
            ],
        }
    )

    assert "Applied 1/3" in result.content
    assert "Edit 1: empty old_content" in result.content
    assert "Edit 2:" in result.content and "not found" in result.content
    assert "ALPHA" in target.read_text()


async def test_multi_edit_ambiguous_match_reported(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("x = 1\nx = 1\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
            "edits": [{"old_content": "x = 1", "new_content": "y = 2"}],
        }
    )

    assert "Applied 0/1" in result.content
    assert "matches 2 locations" in result.content
    assert target.read_text() == "x = 1\nx = 1\n"


async def test_create_file_handler_routes_validation_error(tmp_path):
    tool = make_create_file_tool(tmp_path, None)
    result = await tool.execute({"file": "bad>name.py", "content": "x"})
    assert "file" in result.content
    assert "Invalid arguments" in result.content
    assert not (tmp_path / "bad>name.py").exists()


async def test_read_file_handler_rejects_garbage_file(tmp_path):
    tool = make_read_file_tool(tmp_path, None)
    result = await tool.execute({"file": "file>\nsigil/integrations/github.py", "limit": 30})
    assert "file" in result.content
    assert "Invalid arguments" in result.content


async def test_read_file_handler_valid_passthrough(tmp_path):
    target = tmp_path / "hello.py"
    target.write_text("print('hi')\n")

    tool = make_read_file_tool(tmp_path, None)
    result = await tool.execute({"file": "hello.py"})

    assert "print('hi')" in result.content


@pytest.mark.parametrize(
    "file_text,old_text",
    [
        ("msg = 'hello'\n", "msg = \u2018hello\u2019"),
        ('msg = "hello"\n', "msg = \u201chello\u201d"),
        ("a - b\n", "a \u2014 b"),
        ("a - b\n", "a \u2013 b"),
        ("x = 1\n", "x\u00a0=\u00a01"),
    ],
    ids=["smart_single", "smart_double", "em_dash", "en_dash", "nbsp"],
)
async def test_apply_edit_normalized_match(tmp_path, file_text, old_text):
    target = tmp_path / "f.txt"
    target.write_text(file_text)

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute(
        {"file": "f.txt", "old_content": old_text, "new_content": "REPLACED"}
    )

    assert "Applied edit" in result.content
    assert "(normalized match" in result.content
    assert "REPLACED" in target.read_text()


async def test_apply_edit_normalized_match_marker_text(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("greet = 'hi'\n")

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute(
        {"file": "f.py", "old_content": "greet = \u2018hi\u2019", "new_content": "greet = 'hello'"}
    )

    assert "(normalized match \u2014 smart quotes/dashes/spaces folded to ASCII)" in result.content


def test_paginate_lines_first_line_too_big_at_offset_1():
    big = "x" * (MAX_READ_BYTES + 100) + "\n"
    result = paginate_lines([big, "small\n"], offset=1, file_path="huge.json")
    assert "Line 1 alone is" in result
    assert "sed -n '1p' huge.json" in result
    assert f"head -c {MAX_READ_BYTES}" in result


def test_paginate_lines_first_line_too_big_at_offset_n():
    lines = ["short\n", "short\n", "short\n", "short\n", "x" * (MAX_READ_BYTES + 100) + "\n"]
    result = paginate_lines(lines, offset=5, file_path="bundle.js")
    assert "Line 5 alone is" in result
    assert "sed -n '5p' bundle.js" in result


async def test_apply_edit_noop_returns_error_and_does_not_write(tmp_path):
    target = tmp_path / "f.txt"
    original = "hello\nworld\n"
    target.write_text(original)
    mtime_before = target.stat().st_mtime_ns

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute({"file": "f.txt", "old_content": "hello", "new_content": "hello"})

    assert "No change applied" in result.content
    assert "no-op" in result.content
    assert target.read_text() == original
    assert target.stat().st_mtime_ns == mtime_before


async def test_multi_edit_all_noop_returns_zero_applied(tmp_path):
    target = tmp_path / "f.txt"
    original = "alpha\nbeta\n"
    target.write_text(original)

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.txt",
            "edits": [
                {"old_content": "alpha", "new_content": "alpha"},
                {"old_content": "beta", "new_content": "beta"},
            ],
        }
    )

    assert "Applied 0/2" in result.content
    assert "no-op" in result.content
    assert target.read_text() == original


async def test_multi_edit_mixed_real_and_noop_applies_real(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("alpha\nbeta\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.txt",
            "edits": [
                {"old_content": "alpha", "new_content": "ALPHA"},
                {"old_content": "beta", "new_content": "beta"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert target.read_text() == "ALPHA\nbeta\n"


class TestValidateFileSyntax:
    def test_valid_python_returns_none(self):
        assert _validate_file_syntax("x = 1\n", "test.py") is None

    def test_invalid_python_returns_error(self):
        result = _validate_file_syntax("def foo(\n", "test.py")
        assert result is not None
        assert "SyntaxError" in result

    def test_balanced_non_python_returns_none(self):
        assert _validate_file_syntax("function() { return [1, 2]; }\n", "app.js") is None

    def test_unbalanced_non_python_returns_error(self):
        result = _validate_file_syntax("function() { return [1, 2; }\n", "app.js")
        assert result is not None
        assert "Unbalanced" in result

    def test_binary_extension_skipped(self):
        for ext in (".png", ".svg", ".ico", ".woff", ".lock"):
            assert _validate_file_syntax("anything", f"file{ext}") is None

    def test_python_extension_case_insensitive(self):
        assert _validate_file_syntax("x = 1\n", "test.PY") is None
        result = _validate_file_syntax("def foo(\n", "test.PY")
        assert result is not None

    def test_unbalanced_parens_in_non_python(self):
        result = _validate_file_syntax("func((arg)\n", "config.toml")
        assert result is not None
        assert "Unbalanced" in result

    def test_unbalanced_brackets_in_non_python(self):
        result = _validate_file_syntax("data = [1, 2\n", "data.json")
        assert result is not None

    def test_unbalanced_braces_in_non_python(self):
        result = _validate_file_syntax('{ "key": "val" \n', "data.json")
        assert result is not None


class TestApplyEditValidation:
    def test_syntax_error_reverts_file(self, tmp_path):
        original = "def hello():\n    return 1\n"
        (tmp_path / "app.py").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "app.py")

        result = apply_edit(
            tmp_path,
            "app.py",
            "return 1",
            "return (",
            tracker=tracker,
        )

        assert "Syntax error" in result
        assert "reverted" in result
        assert (tmp_path / "app.py").read_text() == original
        assert tracker.validation_failures == 1

    def test_valid_edit_passes_validation(self, tmp_path):
        original = "def hello():\n    return 1\n"
        (tmp_path / "app.py").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "app.py")

        result = apply_edit(
            tmp_path,
            "app.py",
            "return 1",
            "return 2",
            tracker=tracker,
        )

        assert "Applied edit" in result
        assert (tmp_path / "app.py").read_text() == "def hello():\n    return 2\n"
        assert tracker.validation_failures == 0

    def test_syntax_error_increments_validation_failures(self, tmp_path):
        original = "x = 1\ny = 2\n"
        (tmp_path / "f.py").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "f.py")

        apply_edit(tmp_path, "f.py", "x = 1", "x = (", tracker=tracker)
        assert tracker.validation_failures == 1

        tracker.record_read(tmp_path, "f.py")
        apply_edit(tmp_path, "f.py", "x = 1", "x = (", tracker=tracker)
        assert tracker.validation_failures == 2

    def test_non_python_unbalanced_reverts(self, tmp_path):
        original = "function foo() { return 1; }\n"
        (tmp_path / "app.js").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "app.js")

        result = apply_edit(
            tmp_path,
            "app.js",
            "return 1",
            "return 1; }",
            tracker=tracker,
        )

        assert "Syntax error" in result or "Unbalanced" in result
        assert (tmp_path / "app.js").read_text() == original
        assert tracker.validation_failures == 1

    def test_non_python_balanced_passes(self, tmp_path):
        original = "function foo() { return 1; }\n"
        (tmp_path / "app.js").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "app.js")

        result = apply_edit(
            tmp_path,
            "app.js",
            "return 1",
            "return 2",
            tracker=tracker,
        )

        assert "Applied edit" in result
        assert tracker.validation_failures == 0


class TestMultiEditValidation:
    def test_syntax_error_reverts_all_edits(self, tmp_path):
        original = "def a():\n    return 1\n\ndef b():\n    return 2\n"
        (tmp_path / "app.py").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "app.py")

        result = multi_edit(
            tmp_path,
            "app.py",
            [
                {"old_content": "return 1", "new_content": "return 10"},
                {"old_content": "return 2", "new_content": "return ("},
            ],
            tracker=tracker,
        )

        assert "Syntax error" in result
        assert "reverted" in result
        assert (tmp_path / "app.py").read_text() == original
        assert tracker.validation_failures == 1

    def test_valid_edits_pass_validation(self, tmp_path):
        original = "def a():\n    return 1\n\ndef b():\n    return 2\n"
        (tmp_path / "app.py").write_text(original)
        tracker = FileTracker()
        tracker.record_read(tmp_path, "app.py")

        result = multi_edit(
            tmp_path,
            "app.py",
            [
                {"old_content": "return 1", "new_content": "return 10"},
                {"old_content": "return 2", "new_content": "return 20"},
            ],
            tracker=tracker,
        )

        assert "Applied 2/2" in result
        assert "return 10" in (tmp_path / "app.py").read_text()
        assert "return 20" in (tmp_path / "app.py").read_text()
        assert tracker.validation_failures == 0


class TestFileTrackerValidationFailures:
    def test_starts_at_zero(self):
        tracker = FileTracker()
        assert tracker.validation_failures == 0

    def test_increments(self):
        tracker = FileTracker()
        tracker.validation_failures += 1
        assert tracker.validation_failures == 1
        tracker.validation_failures += 1
        assert tracker.validation_failures == 2
