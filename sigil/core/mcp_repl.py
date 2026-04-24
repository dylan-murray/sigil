import tempfile
from pathlib import Path

from sigil.core.agent import Tool, ToolResult
from sigil.core.utils import StatusCallback, arun

REPL_TIMEOUT = 10
RUN_PYTHON_PARAMS = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "Python code to execute in a fresh subprocess.",
        },
    },
    "required": ["code"],
}


def make_repl_tool(repo: Path, on_status: StatusCallback | None = None) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        code = str(args.get("code", ""))
        if on_status:
            on_status("Running Python hypothesis check...")

        script = f"import sys\nsys.path.insert(0, {str(repo)!r})\n{code}"
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "snippet.py"
            script_path.write_text(script)
            rc, stdout, stderr = await arun(
                ["python", str(script_path)],
                cwd=repo,
                timeout=REPL_TIMEOUT,
            )

        output = stdout
        if stderr:
            output += stderr
        if rc != 0:
            return ToolResult(content=output or f"Python snippet failed with exit code {rc}")
        return ToolResult(content=output or "(no output)")

    return Tool(
        name="run_python",
        description=(
            "Execute a small Python snippet in a fresh subprocess scoped to the repository. "
            "Use this only to test a hypothesis or inspect repository objects; state does not persist between calls."
        ),
        parameters=RUN_PYTHON_PARAMS,
        handler=_handler,
    )
