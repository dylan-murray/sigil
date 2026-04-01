import pytest

from sigil.core.agent import Tool, ToolResult
from sigil.core.tools import create_file, make_read_file_tool


def test_executor_tools_module_exports_helpers(tmp_path):
    tool = make_read_file_tool(tmp_path, None)
    assert isinstance(tool, Tool)

    result = create_file(tmp_path, "example.py", "print('hi')")
    assert result == "Created example.py."


@pytest.mark.asyncio
async def test_read_file_tool_reads_contents(tmp_path):
    file_path = tmp_path / "example.py"
    file_path.write_text("print('hi')\n")

    tool = make_read_file_tool(tmp_path, None)
    result = await tool.execute({"file": "example.py"})

    assert isinstance(result, ToolResult)
    assert "print('hi')" in result.content
