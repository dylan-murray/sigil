import re
from collections.abc import Awaitable, Callable
from fnmatch import fnmatch
from pathlib import Path

from sigil.core.agent import Tool, ToolResult
from sigil.core.utils import StatusCallback, arun, read_file

MAX_FILE_READS = 10
MAX_READ_LINES = 2000
MAX_READ_BYTES = 50_000

HIDDEN_DIRS = {".git", ".sigil", "__pycache__", ".ruff_cache", ".pytest_cache", "node_modules"}


def read_file_paginated(
    path: Path,
    offset: int = 1,
    limit: int = MAX_READ_LINES,
) -> str:
    content = read_file(path)
    if not content:
        return ""

    all_lines = content.splitlines(keepends=True)
    total_lines = len(all_lines)
    start = max(0, offset - 1)
    cap = min(limit, MAX_READ_LINES)
    selected = all_lines[start : start + cap]

    output_lines: list[str] = []
    byte_count = 0
    for line in selected:
        byte_count += len(line.encode())
        if byte_count > MAX_READ_BYTES:
            break
        output_lines.append(line)

    result = "".join(output_lines)
    end_line = start + len(output_lines)

    if end_line < total_lines:
        if not result.endswith("\n"):
            result += "\n"
        result += (
            f"[truncated — {total_lines} lines total. "
            f"Use read_file with offset={end_line + 1} to continue.]"
        )

    return result


def list_directory(
    repo: Path,
    path: str,
    depth: int = 1,
    ignore: list[str] | None = None,
) -> str:
    depth = min(max(depth, 1), 3)
    repo_resolved = repo.resolve()
    target = (repo / path).resolve()
    if not target.is_relative_to(repo_resolved):
        return f"Access denied: {path} is outside the repository."
    if not target.is_dir():
        return f"Not a directory: {path}"
    rel_to_repo = target.relative_to(repo_resolved)
    if any(part in HIDDEN_DIRS or part.startswith(".") for part in rel_to_repo.parts):
        return f"Access denied: {path} is a hidden or internal directory."

    lines: list[str] = []

    def _walk(dir_path: Path, current_depth: int, prefix: str = "") -> None:
        if current_depth > depth:
            return
        try:
            raw = list(dir_path.iterdir())
        except PermissionError:
            return
        tagged = [(p, p.is_dir()) for p in raw]
        tagged.sort(key=lambda t: (not t[1], t[0].name))
        for entry, is_dir in tagged:
            rel = str(entry.relative_to(repo_resolved))
            if entry.name in HIDDEN_DIRS:
                continue
            if entry.name.startswith(".") and is_dir:
                continue
            if ignore and any(fnmatch(rel, p) for p in ignore):
                continue
            if is_dir:
                lines.append(f"{prefix}{entry.name}/")
                if current_depth < depth:
                    _walk(entry, current_depth + 1, prefix=prefix + "  ")
            else:
                lines.append(f"{prefix}{entry.name}")

    _walk(target, 1)

    if not lines:
        return f"Directory {path} is empty."
    return "\n".join(lines)


def make_read_file_handler(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    max_reads: int = MAX_FILE_READS,
    on_read: Callable[[Path, str], None] | None = None,
) -> Callable[[dict], Awaitable[ToolResult]]:
    file_reads = 0
    resolved = repo.resolve()

    async def _handler(args: dict) -> ToolResult:
        nonlocal file_reads
        file_path = str(args.get("file", ""))

        if file_reads >= max_reads:
            return ToolResult(
                content=f"Read limit reached ({max_reads}). Continue with what you have."
            )

        target = (repo / file_path).resolve()
        if not target.is_relative_to(resolved):
            return ToolResult(content=f"Access denied: {file_path} is outside the repository.")
        if ignore and any(fnmatch(file_path, p) for p in ignore):
            return ToolResult(content=f"Access denied: {file_path} is ignored by config.")

        if on_status:
            on_status(f"Reading {file_path}...")

        if not target.exists():
            return ToolResult(content=f"File not found or empty: {file_path}")

        file_reads += 1
        offset = max(1, int(args.get("offset", 1)))
        limit = int(args.get("limit", MAX_READ_LINES))
        content = read_file_paginated(target, offset=offset, limit=limit)

        if not content:
            return ToolResult(content=f"File not found or empty: {file_path}")

        if on_read:
            on_read(repo, file_path)

        return ToolResult(content=content)

    return _handler


def make_read_file_tool(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    description: str | None = None,
    max_reads: int = MAX_FILE_READS,
    on_read: Callable[[Path, str], None] | None = None,
    handler: Callable[[dict], Awaitable[ToolResult]] | None = None,
) -> Tool:
    return Tool(
        name="read_file",
        description=description
        or (
            "Read the contents of a file in the repository. "
            "Large files are truncated — use offset to read further."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "File path relative to the repo root.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, default 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default 2000).",
                },
            },
            "required": ["file"],
        },
        handler=handler
        or make_read_file_handler(
            repo,
            on_status,
            ignore,
            max_reads=max_reads,
            on_read=on_read,
        ),
    )


def make_grep_tool(
    repo: Path,
    on_status: StatusCallback | None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        pattern = str(args.get("pattern", ""))
        search_path = str(args.get("path", "."))
        include = args.get("include", "")

        if on_status:
            on_status(f"Searching for {pattern!r}...")

        target = (repo / search_path).resolve()
        if not target.is_relative_to(repo.resolve()):
            return ToolResult(content="Access denied: search path is outside the repository.")

        if not target.exists():
            return ToolResult(content=f"Path not found: {search_path}")

        try:
            re.compile(pattern)
        except re.error as e:
            return ToolResult(content=f"Invalid regex: {e}")

        cmd = ["grep", "-rn", "--include=*", "-E", pattern]
        if include:
            cmd = ["grep", "-rn", f"--include={include}", "-E", pattern]
        cmd.append(str(target))

        rc, stdout, stderr = await arun(cmd, cwd=repo, timeout=30)

        if not stdout:
            return ToolResult(content=f"No matches found for {pattern!r} in {search_path}")

        lines = stdout.splitlines()
        repo_prefix = str(repo.resolve()) + "/"
        cleaned = [line.replace(repo_prefix, "") for line in lines[:100]]
        truncated = ""
        if len(lines) > 100:
            truncated = f"\n\n[{len(lines)} total matches — showing first 100]"
        return ToolResult(content="\n".join(cleaned) + truncated)

    return Tool(
        name="grep",
        description=(
            "Search file contents in the repository using a regex pattern. "
            "Returns matching file paths and line numbers with context. "
            "Use this to find function definitions, callers, imports, and references."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory or file to search in, relative to repo root. "
                        "Defaults to repo root."
                    ),
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. '*.py', '*.ts').",
                },
            },
            "required": ["pattern"],
        },
        handler=_handler,
    )


def make_list_dir_tool(
    repo: Path,
    ignore: list[str] | None = None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        result = list_directory(
            repo,
            str(args.get("path", ".")),
            depth=int(args.get("depth", 1)),
            ignore=ignore,
        )
        return ToolResult(content=result)

    return Tool(
        name="list_directory",
        description=(
            "List files and subdirectories in a directory. Use this to discover "
            "the project structure before reading or editing files. Returns one "
            "level of contents by default, or recursive with max depth."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to repo root. Use '.' for root.",
                },
                "depth": {
                    "type": "integer",
                    "description": (
                        "Max depth to recurse. 1 = immediate children only (default). "
                        "2 = one level of subdirs. Max 3."
                    ),
                },
            },
            "required": ["path"],
        },
        handler=_handler,
    )
