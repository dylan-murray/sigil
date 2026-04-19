import logging
import re
from collections.abc import Awaitable, Callable
from fnmatch import fnmatch
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from sigil.core.agent import Tool, ToolResult
from sigil.core.llm import format_validation_error_fields, inline_pydantic_schema
from sigil.core.security import is_sensitive_file, is_write_protected, validate_path
from sigil.core.tool_schemas import (
    ApplyEditArgs,
    CreateFileArgs,
    GrepArgs,
    ListDirectoryArgs,
    MultiEditArgs,
    ReadFileArgs,
)
from sigil.core.utils import (
    StatusCallback,
    arun,
    find_all_match_locations,
    find_best_match_region,
    fix_double_escaped,
    format_ambiguous_matches,
    fuzzy_find_match,
    numbered_window,
    read_file,
)
from sigil.pipeline.models import FileTracker, ReviewDecision, ReviewDecisions

logger = logging.getLogger(__name__)

MAX_READ_LINES = 2000
MAX_READ_BYTES = 50_000
MAX_FULL_READS = 3
MAX_READS_HARD_STOP = 10
MAX_EDIT_FAILURES = 3
EDIT_CONTEXT_LINES = 10

HIDDEN_DIRS = {".git", ".sigil", "__pycache__", ".ruff_cache", ".pytest_cache", "node_modules"}


_ToolArgs = TypeVar("_ToolArgs", bound=BaseModel)


def _validate_tool_args(schema: type[_ToolArgs], args: dict) -> tuple[_ToolArgs | None, str | None]:
    try:
        return schema.model_validate(args), None
    except ValidationError as exc:
        fields = format_validation_error_fields(exc)
        return None, f"Invalid arguments — errors on: {fields}. Review the tool schema and retry."


def paginate_lines(
    all_lines: list[str],
    offset: int = 1,
    limit: int = MAX_READ_LINES,
) -> str:
    if not all_lines:
        return ""

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


def paginate_content(
    content: str,
    offset: int = 1,
    limit: int = MAX_READ_LINES,
) -> str:
    if not content:
        return ""
    return paginate_lines(content.splitlines(keepends=True), offset=offset, limit=limit)


def read_file_paginated(
    path: Path,
    offset: int = 1,
    limit: int = MAX_READ_LINES,
) -> str:
    content = read_file(path)
    return paginate_content(content, offset=offset, limit=limit)


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


def _read_file(
    repo: Path,
    file: str,
    offset: int = 1,
    limit: int = MAX_READ_LINES,
    ignore: list[str] | None = None,
) -> str:
    if is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be read."
    path = validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if not path.exists():
        return f"File not found: {file}"
    if not path.is_file():
        return f"Not a file: {file}"

    content = read_file_paginated(path, offset=offset, limit=limit)
    if not content:
        return f"File not found or empty: {file}"
    return content


def _validated_read(
    repo: Path,
    file: str,
    tracker: FileTracker | None = None,
    ignore: list[str] | None = None,
) -> tuple[Path, str] | str:
    if is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be modified."
    if is_write_protected(file):
        return f"Access denied: {file} is managed by Sigil and cannot be modified."
    path = validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if not path.exists():
        return f"File not found: {file}"
    if tracker is not None:
        stale = tracker.check_staleness(repo, file)
        if stale:
            return stale
    try:
        content = path.read_text()
    except OSError as e:
        return f"Cannot read {file}: {e}"
    return path, content


def apply_edit(
    repo: Path,
    file: str,
    old_content: str,
    new_content: str,
    tracker: FileTracker | None = None,
    ignore: list[str] | None = None,
) -> str:
    old_content = fix_double_escaped(old_content)
    new_content = fix_double_escaped(new_content)
    result = _validated_read(repo, file, tracker, ignore)
    if isinstance(result, str):
        return result
    path, content = result

    if not old_content.strip():
        total_lines = len(content.splitlines())
        return (
            f"old_content is empty. To INSERT code, include a few lines of existing "
            f"code as old_content (the anchor), then put those same lines PLUS your "
            f"new code as new_content. Example: old_content='def foo():\\n    pass' "
            f"new_content='def foo():\\n    pass\\n\\ndef bar():\\n    return 1'. "
            f"Use read_file to find the right anchor point in {file} ({total_lines} lines)."
        )

    count = content.count(old_content)
    matched_text = old_content
    fuzzy_info = ""

    if count == 0:
        fuzzy_result = fuzzy_find_match(content, old_content)
        if fuzzy_result is None:
            total_lines = len(content.splitlines())
            region = find_best_match_region(content, old_content)
            return (
                f"old_content not found in {file} ({total_lines} lines). "
                f"The old_content must match the file EXACTLY, including whitespace "
                f"and indentation. Re-read the file with read_file and copy the exact "
                f"text you want to replace.\n\n{region}"
            )
        matched_text, ratio, match_line = fuzzy_result
        count = content.count(matched_text)
        fuzzy_info = f" (fuzzy match {ratio:.0%} at line {match_line})"
        logger.info("Fuzzy match in %s: %.1f%% at line %d", file, ratio * 100, match_line)

    if count > 1:
        return format_ambiguous_matches(content, matched_text, file)

    new_file_content = content.replace(matched_text, new_content, 1)
    path.write_text(new_file_content)

    if tracker is not None:
        tracker.modified.add(file)
        tracker.cache_content(file, new_file_content)
        tracker.record_read(repo, file)

    new_lines = new_file_content.splitlines()
    edit_start = content[: content.index(matched_text)].count("\n")
    edit_end = edit_start + new_content.count("\n")
    edit_center = (edit_start + edit_end) // 2
    context_window = numbered_window(new_lines, edit_center)

    return f"Applied edit to {file}{fuzzy_info}.\n\nCurrent state around edit:\n\n{context_window}"


def create_file(
    repo: Path,
    file: str,
    content: str,
    tracker: FileTracker | None = None,
    ignore: list[str] | None = None,
) -> str:
    if is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be created."
    if is_write_protected(file):
        return f"Access denied: {file} is managed by Sigil and cannot be created."
    path = validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if path.exists() and (tracker is None or file not in tracker.created):
        return f"File already exists: {file}. Use apply_edit to modify it."
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if tracker is not None:
            tracker.created.add(file)
            tracker.cache_content(file, content)
            tracker.record_read(repo, file)
        return f"Created {file}."
    except OSError as e:
        return f"Cannot create {file}: {e}"


def multi_edit(
    repo: Path,
    file: str,
    edits: list[dict],
    tracker: FileTracker | None = None,
    ignore: list[str] | None = None,
) -> str:
    if not isinstance(edits, list) or not edits:
        return "edits must be a non-empty list."

    vr = _validated_read(repo, file, tracker, ignore)
    if isinstance(vr, str):
        return vr
    path, content = vr

    applied = 0
    failed = []
    for i, edit in enumerate(edits):
        old = fix_double_escaped(str(edit.get("old_content", "")))
        new = fix_double_escaped(str(edit.get("new_content", "")))
        if not old.strip():
            failed.append(f"Edit {i}: empty old_content")
            continue
        if old not in content:
            failed.append(f"Edit {i}: old_content not found")
            continue
        if content.count(old) > 1:
            locs = find_all_match_locations(content, old)
            loc_str = ", ".join(str(ln) for ln in locs[:5])
            failed.append(f"Edit {i}: old_content matches {len(locs)} locations (lines {loc_str})")
            continue
        content = content.replace(old, new, 1)
        applied += 1

    if applied > 0:
        path.write_text(content)
        if tracker is not None:
            tracker.modified.add(file)
            tracker.cache_content(file, content)
            tracker.record_read(repo, file)

    parts = [f"Applied {applied}/{len(edits)} edits to {file}."]
    if failed:
        parts.append("Failed edits:\n" + "\n".join(f"  - {f}" for f in failed))
    parts.append(f"\nFile now has {len(content.splitlines())} lines.")
    return "\n".join(parts)


def make_read_file_handler(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    tracker: FileTracker | None = None,
    on_read: Callable[[Path, str], None] | None = None,
) -> Callable[[dict], Awaitable[ToolResult]]:
    resolved = repo.resolve()

    async def _handler(args: dict) -> ToolResult:
        parsed, err = _validate_tool_args(ReadFileArgs, args)
        if parsed is None:
            return ToolResult(content=err or "")
        file_path = parsed.file

        target = (repo / file_path).resolve()
        if not target.is_relative_to(resolved):
            return ToolResult(content=f"Access denied: {file_path} is outside the repository.")
        if ignore and any(fnmatch(file_path, p) for p in ignore):
            return ToolResult(content=f"Access denied: {file_path} is ignored by config.")

        if tracker is not None:
            offset = parsed.offset
            key = f"{file_path}:{offset}"
            key_count = tracker.read_keys.get(key, 0)
            tracker.read_keys[key] = key_count + 1
            file_total = tracker.read_totals.get(file_path, 0)
            tracker.read_totals[file_path] = file_total + 1
            needs_reread = file_path not in tracker.last_read

            if file_total >= MAX_READS_HARD_STOP:
                return ToolResult(
                    content=f"READ LIMIT: {file_path} has been read {file_total} times.",
                    nudge=(
                        f"You have read {file_path} {file_total} times and are blocked from "
                        f"reading it again. You have enough context — STOP reading this file and "
                        f"make progress via apply_edit, multi_edit, or create_file. If you are "
                        f"truly stuck, call task_progress with a failure reason."
                    ),
                )

            if key_count >= MAX_FULL_READS and not needs_reread:
                if file_path in tracker.modified:
                    return ToolResult(
                        content=f"DOOM LOOP: re-reading {file_path} at the same offset.",
                        nudge=(
                            f"You are re-reading {file_path} at the same offset without making "
                            f"progress. STOP and re-think your approach. If apply_edit keeps "
                            f"failing with 'matches N locations', include MORE surrounding "
                            f"context in old_content to make it unique. If you cannot make "
                            f"progress, call task_progress to report what went wrong."
                        ),
                    )

        if on_status:
            on_status(f"Reading {file_path}...")

        if not target.exists():
            return ToolResult(content=f"File not found or empty: {file_path}")

        offset = max(1, parsed.offset)
        limit = parsed.limit

        try:
            current_mtime = target.stat().st_mtime
        except OSError:
            current_mtime = None
        cached_mtime = tracker.last_read.get(file_path) if tracker is not None else None
        cache_hit = (
            tracker is not None
            and cached_mtime is not None
            and current_mtime is not None
            and current_mtime == cached_mtime
            and tracker.get_cached_content(file_path) is not None
        )

        if cache_hit:
            cached_lines = tracker.get_cached_lines(file_path) or []
            content = paginate_lines(cached_lines, offset=offset, limit=limit)
        else:
            full_content = read_file(target)
            if not full_content:
                return ToolResult(content=f"File not found or empty: {file_path}")
            if tracker is not None:
                tracker.cache_content(file_path, full_content)
            content = paginate_content(full_content, offset=offset, limit=limit)

        if not content:
            return ToolResult(content=f"File not found or empty: {file_path}")

        if on_read:
            on_read(repo, file_path)

        if tracker is not None:
            tracker.record_read(repo, file_path)

        return ToolResult(content=content)

    return _handler


def make_read_file_tool(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    description: str | None = None,
    on_read: Callable[[Path, str], None] | None = None,
    handler: Callable[[dict], Awaitable[ToolResult]] | None = None,
    tracker: FileTracker | None = None,
) -> Tool:
    return Tool(
        name="read_file",
        description=description
        or (
            "Read the contents of a file in the repository. "
            "Large files are truncated — use offset to read further."
        ),
        parameters=inline_pydantic_schema(ReadFileArgs),
        handler=handler
        or make_read_file_handler(
            repo,
            on_status,
            ignore,
            on_read=on_read,
            tracker=tracker,
        ),
    )


def _grep_exclude_dirs(ignore: list[str] | None) -> list[str]:
    if not ignore:
        return []
    dirs: set[str] = set()
    for pattern in ignore:
        if pattern.endswith("/**"):
            name = pattern[:-3]
            if "/" not in name and "*" not in name:
                dirs.add(name)
    return sorted(dirs)


def make_grep_tool(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
) -> Tool:
    exclude_dirs = _grep_exclude_dirs(ignore)

    async def _handler(args: dict) -> ToolResult:
        parsed, err = _validate_tool_args(GrepArgs, args)
        if parsed is None:
            return ToolResult(content=err or "")
        pattern = parsed.pattern
        search_path = parsed.path
        include = parsed.include

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

        cmd = ["grep", "-rnI", "-E", pattern]
        cmd.append(f"--include={include}" if include else "--include=*")
        for d in exclude_dirs:
            cmd.append(f"--exclude-dir={d}")
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
        parameters=inline_pydantic_schema(GrepArgs),
        handler=_handler,
    )


def make_list_dir_tool(
    repo: Path,
    ignore: list[str] | None = None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        parsed, err = _validate_tool_args(ListDirectoryArgs, args)
        if parsed is None:
            return ToolResult(content=err or "")
        result = list_directory(repo, parsed.path, depth=parsed.depth, ignore=ignore)
        return ToolResult(content=result)

    return Tool(
        name="list_directory",
        description=(
            "List files and subdirectories in a directory. Use this to discover "
            "the project structure before reading or editing files. Returns one "
            "level of contents by default, or recursive with max depth."
        ),
        parameters=inline_pydantic_schema(ListDirectoryArgs),
        handler=_handler,
    )


def make_apply_edit_tool(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    tracker: FileTracker | None = None,
) -> Tool:
    edit_failures: dict[str, int] = {}

    async def _handler(args: dict) -> ToolResult:
        parsed, err = _validate_tool_args(ApplyEditArgs, args)
        if parsed is None:
            return ToolResult(content=err or "")
        if on_status:
            on_status(f"Editing {parsed.file}...")
        result = apply_edit(
            repo,
            parsed.file,
            parsed.old_content,
            parsed.new_content,
            tracker=tracker,
            ignore=ignore,
        )
        if "Applied edit" in result:
            edit_failures.pop(parsed.file, None)
        elif "not found" in result or "matches" in result:
            count = edit_failures.get(parsed.file, 0) + 1
            edit_failures[parsed.file] = count
            if count >= MAX_EDIT_FAILURES:
                edit_failures[parsed.file] = 0
                result += (
                    f"\n\nYou have failed to edit {parsed.file} {count} times in a row. "
                    f"STOP trying the same approach. You MUST re-read the file with "
                    f"read_file before your next apply_edit call on this file."
                )
        return ToolResult(content=result)

    return Tool(
        name="apply_edit",
        description=(
            "Apply a code edit to a file. Provide the exact content to find and "
            "the content to replace it with. Call once per edit."
        ),
        parameters=inline_pydantic_schema(ApplyEditArgs),
        handler=_handler,
        mutating=True,
    )


def make_multi_edit_tool(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    tracker: FileTracker | None = None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        parsed, err = _validate_tool_args(MultiEditArgs, args)
        if parsed is None:
            return ToolResult(content=err or "")
        if on_status:
            on_status(f"Multi-editing {parsed.file}...")
        edits = [e.model_dump() for e in parsed.edits]
        result = multi_edit(repo, parsed.file, edits, tracker=tracker, ignore=ignore)
        return ToolResult(content=result)

    return Tool(
        name="multi_edit",
        description=(
            "Apply multiple sequential edits to a SINGLE file atomically. "
            "Each edit is a find-and-replace pair. Earlier edits transform "
            "the file content for later edits. Use this when you need to "
            "make several changes to the same file."
        ),
        parameters=inline_pydantic_schema(MultiEditArgs),
        handler=_handler,
        mutating=True,
    )


def make_create_file_tool(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
    *,
    tracker: FileTracker | None = None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        parsed, err = _validate_tool_args(CreateFileArgs, args)
        if parsed is None:
            return ToolResult(content=err or "")
        if on_status:
            on_status(f"Creating {parsed.file}...")
        result = create_file(
            repo,
            parsed.file,
            fix_double_escaped(parsed.content),
            tracker=tracker,
            ignore=ignore,
        )
        return ToolResult(content=result)

    return Tool(
        name="create_file",
        description="Create a new file with the given content.",
        parameters=inline_pydantic_schema(CreateFileArgs),
        handler=_handler,
        mutating=True,
    )


def make_task_progress_tool(
    tracker: FileTracker,
) -> Tool:
    last_progress_snapshot: tuple[frozenset[str], frozenset[str]] | None = None

    async def _handler(args: dict) -> ToolResult:
        nonlocal last_progress_snapshot

        created = sorted(tracker.created) if tracker.created else []
        modified = sorted(tracker.modified) if tracker.modified else []
        current_snapshot = (frozenset(created), frozenset(modified))

        if not created and not modified:
            if last_progress_snapshot == current_snapshot:
                return ToolResult(
                    content="No changes were made. Stopping.",
                    stop=True,
                    result=args.get("summary", ""),
                )
            last_progress_snapshot = current_snapshot
            return ToolResult(
                content=(
                    "HOLD ON — you have not made any changes yet. "
                    "No files were created or modified.\n\n"
                    "Go back and implement the task. Use apply_edit and create_file "
                    "to make the actual code changes, then call task_progress again."
                ),
            )

        has_summary = bool(args.get("summary", "").strip())
        seen_before = last_progress_snapshot == current_snapshot

        if seen_before or has_summary:
            return ToolResult(
                content="Done acknowledged.",
                stop=True,
                result=args.get("summary"),
            )

        last_progress_snapshot = current_snapshot

        checklist = "Progress check:\n\n"
        checklist += f"Files you CREATED: {', '.join(created) if created else '(none)'}\n"
        checklist += f"Files you MODIFIED: {', '.join(modified) if modified else '(none)'}\n\n"
        checklist += (
            "Review the task description again. Did you:\n"
            "- Make ALL the changes described in the task (not just part of it)?\n"
            "- Wire new modules into existing code (imports, function calls)?\n"
            "- Write or update tests?\n\n"
            "If something is missing, go fix it now. "
            "If everything is genuinely complete, call task_progress again with your summary."
        )

        return ToolResult(content=checklist)

    return Tool(
        name="task_progress",
        description=(
            "Check your progress on the task. Call this when you think you are done. "
            "The system will show you exactly which files you created and modified, "
            "and verify whether the implementation is complete. If anything is missing, "
            "you will be told what to fix. If everything is complete, call it again "
            "with your final summary to finish."
        ),
        parameters={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "A thorough, reviewer-friendly description of your changes. "
                        "This MUST be at least 200 characters. Do NOT use markdown headers (##). "
                        "Write a bulleted list covering:\n"
                        "- What problem this solves and why the change is needed\n"
                        "- Each file changed: what was modified and why\n"
                        "- New functions/classes added: name, purpose, signature\n"
                        "- Tests added or updated: what they verify\n"
                        "- Integration: how the new code connects to existing code\n"
                        "- Key decisions: why you chose this approach over alternatives\n\n"
                        "Example:\n"
                        "- Added `parse_config()` in `config.py` to validate YAML config "
                        "against a Pydantic schema, replacing the raw dict approach that "
                        "silently accepted invalid keys.\n"
                        "- Updated `cli.py:main()` to call `parse_config()` on startup and "
                        "surface validation errors with clear messages.\n"
                        "- Added `tests/test_config.py` with 4 parametrized cases covering "
                        "valid config, missing required fields, invalid types, and extra keys.\n"
                        "- Chose Pydantic over dataclasses because the project already uses "
                        "it for API models."
                    ),
                },
            },
            "required": ["summary"],
        },
        handler=_handler,
    )


def make_verify_hook_tool(
    repo: Path,
    failed_hooks: list[str],
    on_status: StatusCallback | None = None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        results: list[str] = []
        all_passed = True
        for hook in failed_hooks:
            if on_status:
                on_status(f"Verifying fix: {hook}...")
            rc, stdout, stderr = await arun(hook, cwd=repo, timeout=120)
            output = (stdout + "\n" + stderr).strip()
            if rc == 0:
                results.append(f"PASS: `{hook}`")
            else:
                all_passed = False
                truncated = output[-2000:] if len(output) > 2000 else output
                results.append(f"FAIL: `{hook}`\n```\n{truncated}\n```")

        summary = "\n\n".join(results)
        if all_passed:
            summary += "\n\nAll hooks passed. Call task_progress with your summary to finish."
        else:
            summary += "\n\nSome hooks still failing. Fix the remaining issues."
        return ToolResult(content=summary)

    return Tool(
        name="verify_hook",
        description=(
            "Re-run the failed post-hooks to verify your fix works. "
            "Call this AFTER making edits to check if the errors are resolved "
            "before calling task_progress."
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=_handler,
    )


def make_veto_duplicates_tool(
    decisions: ReviewDecisions,
    total: int,
    on_status: StatusCallback | None = None,
) -> Tool:
    async def _handler(args: dict) -> ToolResult:
        pairs = args.get("duplicate_pairs", [])
        if not isinstance(pairs, list):
            return ToolResult(content="duplicate_pairs must be a list of [keep, veto] pairs.")
        vetoed = 0
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            keep_idx, veto_idx = pair
            if not isinstance(keep_idx, int) or not isinstance(veto_idx, int):
                continue
            if veto_idx < 0 or veto_idx >= total:
                continue
            if veto_idx in decisions and decisions[veto_idx].action == "veto":
                continue
            decisions[veto_idx] = ReviewDecision(
                action="veto",
                new_disposition=None,
                reason=f"Duplicate of item [{keep_idx}]",
            )
            vetoed += 1
        if on_status:
            on_status(f"Vetoed {vetoed} duplicate(s)")
        return ToolResult(content=f"Vetoed {vetoed} duplicate(s).")

    return Tool(
        name="veto_duplicates",
        description=(
            "Veto duplicate items in bulk. Call this FIRST, before reviewing "
            "individual items. Pass pairs of [keep_index, veto_index] where "
            "keep_index is the item to keep and veto_index is the duplicate to remove."
        ),
        parameters={
            "type": "object",
            "properties": {
                "duplicate_pairs": {
                    "type": "array",
                    "description": (
                        "List of [keep_index, veto_index] pairs. "
                        "Each pair identifies a duplicate: keep the first, veto the second."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
            },
            "required": ["duplicate_pairs"],
        },
        handler=_handler,
    )


def make_executor_tools(
    repo: Path,
    tracker: FileTracker,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
) -> list[Tool]:
    return [
        make_read_file_tool(repo, on_status, ignore, tracker=tracker),
        make_apply_edit_tool(repo, on_status, ignore, tracker=tracker),
        make_multi_edit_tool(repo, on_status, ignore, tracker=tracker),
        make_create_file_tool(repo, on_status, ignore, tracker=tracker),
        make_grep_tool(repo, on_status, ignore),
        make_list_dir_tool(repo, ignore),
        make_task_progress_tool(tracker),
    ]
