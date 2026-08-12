from unittest.mock import patch

from sigil.core.mcp_repl import make_repl_tool


async def test_run_python_happy_path(tmp_path):
    tool = make_repl_tool(tmp_path)
    result = await tool.execute({"code": "print('hello')"})
    assert "hello" in result.content


async def test_run_python_imports_repo_module(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("VALUE = 42\n")
    tool = make_repl_tool(tmp_path)
    result = await tool.execute({"code": "from pkg import VALUE\nprint(VALUE)"})
    assert "42" in result.content


async def test_run_python_returns_runtime_error(tmp_path):
    tool = make_repl_tool(tmp_path)
    result = await tool.execute({"code": "raise RuntimeError('boom')"})
    assert "RuntimeError" in result.content or "boom" in result.content


async def test_run_python_times_out(tmp_path):
    tool = make_repl_tool(tmp_path)
    with patch("sigil.core.mcp_repl.REPL_TIMEOUT", 0.01):
        result = await tool.execute({"code": "while True:\n    pass"})
    assert "timed out" in result.content.lower() or "timeout" in result.content.lower()
