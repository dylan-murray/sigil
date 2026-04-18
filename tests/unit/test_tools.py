from sigil.core.tools import (
    make_apply_edit_tool,
    make_create_file_tool,
    make_multi_edit_tool,
    make_read_file_tool,
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
