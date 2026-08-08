import pytest

from sigil.core.tools import (
    MAX_READ_BYTES,
    apply_edit,
    create_file,
    make_apply_edit_tool,
    make_create_file_tool,
    make_grep_tool,
    make_multi_edit_tool,
    make_read_file_tool,
    paginate_lines,
)


async def test_apply_edit_handler_regression(tmp_path):
    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute({"file": "f.py", "new_content": "x"})
    assert "old_content" in result.content
    assert "Invalid arguments" in result.content


async def test_apply_edit_handler_valid_passthrough(tmp_path):
    target = tmp_path / "greet.py"
    target.write_text("hello\nworld\n")

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "greet.py",
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
    target = tmp_path / "f.py"
    target.write_text("A\nB\nC\nD\nE\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
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
    target = tmp_path / "f.py"
    target.write_text("line 1\nline 2\nline 3\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
            "edits": [
                {"old_content": "line 1", "new_content": "first"},
                {"old_content": "line 3", "new_content": "third updated"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert target.read_text() == "first\nline 2\nthird updated\n"


async def test_multi_edit_normalized_fallback(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("hello 'world'\nbye 'now'\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
            "edits": [
                {"old_content": "‘world’", "new_content": "WORLD"},
                {"old_content": "‘now’", "new_content": "NOW"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert "(normalized" in result.content
    text = target.read_text()
    assert "WORLD" in text
    assert "NOW" in text


async def test_multi_edit_partial_failure_reports_each(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("alpha\nbeta\ngamma\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
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
        ("msg = 'hello'\n", "msg = ‘hello’"),
        ('msg = "hello"\n', "msg = “hello”"),
        ("a - b\n", "a — b"),
        ("a - b\n", "a – b"),
        ("x = 1\n", "x = 1"),
    ],
    ids=["smart_single", "smart_double", "em_dash", "en_dash", "nbsp"],
)
async def test_apply_edit_normalized_match(tmp_path, file_text, old_text):
    target = tmp_path / "f.py"
    target.write_text(file_text)

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute(
        {"file": "f.py", "old_content": old_text, "new_content": "REPLACED"}
    )

    assert "Applied edit" in result.content
    assert "(normalized match" in result.content
    assert "REPLACED" in target.read_text()


async def test_apply_edit_normalized_match_marker_text(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("greet = 'hi'\n")

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute(
        {"file": "f.py", "old_content": "greet = ‘hi’", "new_content": "greet = 'hello'"}
    )

    assert "(normalized match — smart quotes/dashes/spaces folded to ASCII)" in result.content


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
    target = tmp_path / "f.py"
    original = "hello\nworld\n"
    target.write_text(original)
    mtime_before = target.stat().st_mtime_ns

    tool = make_apply_edit_tool(tmp_path, None)
    result = await tool.execute({"file": "f.py", "old_content": "hello", "new_content": "hello"})

    assert "No change applied" in result.content
    assert "no-op" in result.content
    assert target.read_text() == original
    assert target.stat().st_mtime_ns == mtime_before


async def test_multi_edit_all_noop_returns_zero_applied(tmp_path):
    target = tmp_path / "f.py"
    original = "alpha\nbeta\n"
    target.write_text(original)

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
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
    target = tmp_path / "f.py"
    target.write_text("alpha\nbeta\n")

    tool = make_multi_edit_tool(tmp_path, None)
    result = await tool.execute(
        {
            "file": "f.py",
            "edits": [
                {"old_content": "alpha", "new_content": "ALPHA"},
                {"old_content": "beta", "new_content": "beta"},
            ],
        }
    )

    assert "Applied 2/2" in result.content
    assert target.read_text() == "ALPHA\nbeta\n"


def test_apply_edit_not_found_includes_suggestions(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    pass\n")
    result = apply_edit(
        tmp_path,
        "src/app.py",
        "nonexistent_text_here",
        "replacement",
    )
    assert "not found" in result
    assert "Suggestions" in result
    assert "Re-read" in result
    assert "whitespace" in result
    assert "smaller" in result


def test_create_file_already_exists_suggests_apply_edit(tmp_path):
    (tmp_path / "existing.py").write_text("x = 1\n")
    result = create_file(tmp_path, "existing.py", "y = 2\n")
    assert "already exists" in result
    assert "apply_edit" in result
    assert "different path" in result


async def test_grep_no_matches_includes_suggestions(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    pass\n")
    tool = make_grep_tool(tmp_path, None)
    result = await tool.execute({"pattern": "z_nonexistent_xyz", "path": "src"})
    assert "No matches found" in result.content
    assert "broaden" in result.content
    assert "simpler" in result.content


async def test_read_file_not_found_lists_siblings(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "src" / "utils.py").write_text("y = 2\n")
    (tmp_path / "src" / "models.py").write_text("z = 3\n")
    tool = make_read_file_tool(tmp_path, None)
    result = await tool.execute({"file": "src/nonexistent.py"})
    assert "not found" in result.content.lower()
    assert "app.py" in result.content
    assert "utils.py" in result.content
    assert "models.py" in result.content


async def test_read_file_not_found_no_parent_dir(tmp_path):
    tool = make_read_file_tool(tmp_path, None)
    result = await tool.execute({"file": "nonexistent_dir/missing.py"})
    assert "not found" in result.content.lower()
    assert "list_directory" in result.content


def test_read_file_sync_not_found_suggests_list_directory(tmp_path):
    from sigil.core.tools import _read_file

    result = _read_file(tmp_path, "nonexistent.py")
    assert "not found" in result
    assert "list_directory" in result
