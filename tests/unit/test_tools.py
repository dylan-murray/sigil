import pytest

from sigil.core.security import is_binary_file
from sigil.core.tools import (
    apply_edit,
    create_file,
    make_apply_edit_tool,
    make_create_file_tool,
    make_multi_edit_tool,
    make_read_file_tool,
    multi_edit,
)
from sigil.pipeline.models import FileTracker


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
    "extension,expected",
    [
        (".pyc", True),
        (".png", True),
        (".exe", True),
        (".so", True),
        (".dll", True),
        (".pdf", True),
        (".zip", True),
        (".sqlite", True),
        (".py", False),
        (".json", False),
        (".yaml", False),
        (".toml", False),
        (".md", False),
        (".txt", False),
        (".cfg", False),
    ],
)
def test_is_binary_file(extension, expected):
    assert is_binary_file(f"foo{extension}") == expected


def test_apply_edit_rejects_binary_file(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "image.png")
    result = apply_edit(tmp_path, "image.png", "old", "new", tracker=tracker)
    assert "Cannot edit binary file" in result
    assert "image.png" in result


def test_apply_edit_rejects_whole_file_deletion(tmp_path):
    content = "def hello():\n    return 1\n"
    (tmp_path / "foo.py").write_text(content)
    tracker = FileTracker()
    tracker.record_read(tmp_path, "foo.py")
    result = apply_edit(tmp_path, "foo.py", content, "", tracker=tracker)
    assert "Whole-file deletion blocked" in result


def test_apply_edit_allows_partial_deletion(tmp_path):
    (tmp_path / "foo.py").write_text("def hello():\n    return 1\n\ndef bar():\n    return 2\n")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "foo.py")
    result = apply_edit(tmp_path, "foo.py", "\ndef bar():\n    return 2\n", "\n", tracker=tracker)
    assert "Applied edit" in result


def test_apply_edit_rejects_per_edit_line_cap(tmp_path):
    old_lines = "\n".join(f"line_{i}" for i in range(5))
    new_lines = "\n".join(f"new_{i}" for i in range(20))
    (tmp_path / "big.py").write_text(old_lines + "\n")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "big.py")
    result = apply_edit(
        tmp_path,
        "big.py",
        old_lines,
        new_lines,
        tracker=tracker,
        max_lines_per_edit=10,
    )
    assert "Edit too large" in result
    assert "limit is 10" in result


def test_apply_edit_rejects_total_line_cap(tmp_path):
    (tmp_path / "foo.py").write_text("def hello():\n    return 1\n")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "foo.py")
    tracker.total_lines_changed = 1999
    old_content = "return 1"
    new_content = "\n".join(f"new_line_{i}" for i in range(5))
    result = apply_edit(
        tmp_path,
        "foo.py",
        old_content,
        new_content,
        tracker=tracker,
        max_total_lines_changed=2000,
    )
    assert "Total line change limit exceeded" in result


def test_apply_edit_increments_total_lines_changed(tmp_path):
    (tmp_path / "foo.py").write_text("def hello():\n    return 1\n")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "foo.py")
    result = apply_edit(tmp_path, "foo.py", "return 1", "return 2", tracker=tracker)
    assert "Applied edit" in result
    assert tracker.total_lines_changed > 0


def test_create_file_rejects_binary(tmp_path):
    tracker = FileTracker()
    result = create_file(tmp_path, "image.png", "data", tracker=tracker)
    assert "Cannot create binary file" in result
    assert "image.png" in result


def test_create_file_increments_total_lines_changed(tmp_path):
    tracker = FileTracker()
    result = create_file(tmp_path, "new.py", "line1\nline2\nline3\n", tracker=tracker)
    assert "Created" in result
    assert tracker.total_lines_changed == 4


def test_multi_edit_rejects_binary(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    tracker = FileTracker()
    result = multi_edit(
        tmp_path,
        "image.png",
        [{"old_content": "old", "new_content": "new"}],
        tracker=tracker,
    )
    assert "Cannot edit binary file" in result


def test_multi_edit_per_edit_line_cap(tmp_path):
    (tmp_path / "foo.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "foo.py")
    result = multi_edit(
        tmp_path,
        "foo.py",
        [{"old_content": "def a():\n    return 1", "new_content": "x\n" * 600}],
        tracker=tracker,
        max_lines_per_edit=10,
    )
    assert "Edit 0" in result
    assert "too large" in result


def test_multi_edit_increments_total_lines_changed(tmp_path):
    (tmp_path / "foo.py").write_text("a\nb\nc\n")
    tracker = FileTracker()
    tracker.record_read(tmp_path, "foo.py")
    result = multi_edit(
        tmp_path,
        "foo.py",
        [{"old_content": "a", "new_content": "x"}, {"old_content": "b", "new_content": "y"}],
        tracker=tracker,
    )
    assert "Applied 2/2" in result
    assert tracker.total_lines_changed > 0
