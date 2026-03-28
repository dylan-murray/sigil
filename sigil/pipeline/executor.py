import asyncio
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sigil.core.agent import Agent, AgentCoordinator, Tool, ToolResult
from sigil.core.config import Config
from sigil.core.instructions import Instructions
from sigil.core.llm import (
    acompletion,
    get_usage_snapshot,
    reset_trace_task,
    set_trace_task,
    supports_prompt_caching,
)
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.core.security import is_sensitive_file, is_write_protected, validate_path
from sigil.core.tools import (
    MAX_READ_LINES,
    list_directory,
    make_grep_tool,
    make_list_dir_tool,
    make_read_file_tool,
    read_file_paginated,
)
from sigil.core.utils import (
    StatusCallback,
    arun,
    find_best_match_region,
    fix_double_escaped,
    now_utc,
    numbered_window,
    read_file,
)
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.knowledge import select_memory
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.models import (
    ExecutionResult,
    FailureType,
    ItemDoneCallback,
    ItemStatusCallback,
)
from sigil.pipeline.prompts import (
    ARCHITECT_CONTEXT_PROMPT,
    ARCHITECT_SYSTEM_PROMPT,
    ENGINEER_SYSTEM_PROMPT,
    EXECUTOR_CONTEXT_PROMPT,
    EXECUTOR_TASK_PROMPT,
    EXECUTOR_TASK_PROMPT_WITH_PLAN,
    HOOK_FIX_INJECT_PROMPT,
    HOOK_SUMMARIZE_PROMPT,
)
from sigil.state.attempts import AttemptRecord, format_attempt_history, log_attempt, read_attempts
from sigil.state.chronic import WorkItem, fingerprint as item_fingerprint, slugify
from sigil.state.memory import load_working

log = logging.getLogger(__name__)

COMMAND_TIMEOUT = 120
OUTPUT_TRUNCATE_CHARS = 12000
MIN_SUMMARY_LENGTH = 200
MAX_PRELOAD_FILES = 15
MAX_PRELOAD_BYTES = 100_000
MAX_FULL_READS = 3
MAX_READS_HARD_STOP = 10
EDIT_CONTEXT_LINES = 10
DIFF_PER_FILE_CAP = 4000
DIFF_TOTAL_CAP = 15000
MAX_REVIEWER_TOOL_CALLS = 20
WORKTREE_DIR = ".sigil/worktrees"


def _coerce_read_args(args: dict) -> tuple[int, int]:
    raw_offset = args.get("offset", 1)
    raw_limit = args.get("limit", MAX_READ_LINES)
    if isinstance(raw_offset, list):
        raw_offset = raw_offset[0] if raw_offset else 1
    if isinstance(raw_limit, list):
        raw_limit = raw_limit[0] if raw_limit else MAX_READ_LINES
    return int(raw_offset), int(raw_limit)


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


def _describe_item(item: WorkItem) -> str:
    if isinstance(item, Finding):
        loc = item.file
        if item.line:
            loc = f"{item.file}:{item.line}"
        parts = [
            f"Category: {item.category}",
            f"Location: {loc}",
            f"Problem: {item.description}",
            f"Suggested fix: {item.suggested_fix}",
        ]
        if item.implementation_spec:
            parts.append(f"\n## Implementation Spec\n{item.implementation_spec}")
        return "\n".join(parts)
    parts = [
        f"Feature: {item.title}",
        f"Description: {item.description}",
        f"Complexity: {item.complexity}",
    ]
    if item.implementation_spec:
        parts.append(f"\n## Implementation Spec\n{item.implementation_spec}")
    return "\n".join(parts)


def _preload_relevant_files(
    repo: Path,
    item: WorkItem,
    ignore: list[str] | None = None,
    tracker: "_ChangeTracker | None" = None,
) -> str:
    file_paths: list[str] = list(item.relevant_files)
    if isinstance(item, Finding) and item.file and item.file not in file_paths:
        file_paths.insert(0, item.file)

    if not file_paths:
        return ""

    parts: list[str] = []
    total_bytes = 0
    for rel_path in file_paths[:MAX_PRELOAD_FILES]:
        if ignore and any(rel_path == p or Path(rel_path).match(p) for p in ignore):
            continue
        full = repo / rel_path
        resolved = full.resolve()
        if not resolved.is_relative_to(repo.resolve()):
            continue
        content = read_file(resolved)
        if not content:
            continue
        if total_bytes + len(content.encode()) > MAX_PRELOAD_BYTES:
            lines = content.splitlines(keepends=True)
            budget = MAX_PRELOAD_BYTES - total_bytes
            trimmed: list[str] = []
            used = 0
            for line in lines:
                line_bytes = len(line.encode())
                if used + line_bytes > budget:
                    break
                trimmed.append(line)
                used += line_bytes
            if trimmed:
                content = "".join(trimmed) + f"\n[truncated — {len(lines)} lines total]"
            else:
                continue
        total_bytes += len(content.encode())
        parts.append(f"### {rel_path}\n```\n{content}\n```")
        if tracker is not None:
            tracker.record_read(repo, rel_path)
        if total_bytes >= MAX_PRELOAD_BYTES:
            break

    if not parts:
        return ""

    return "## Pre-loaded Files\n\n" + "\n\n".join(parts)


def _build_cached_message(model: str, context: str, task: str) -> dict:
    if supports_prompt_caching(model):
        return {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": context,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": task,
                },
            ],
        }
    return {"role": "user", "content": context + "\n" + task}


def _validated_read(
    repo: Path,
    file: str,
    tracker: "_ChangeTracker",
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
    stale = tracker.check_staleness(repo, file)
    if stale:
        return stale
    try:
        content = path.read_text()
    except OSError as e:
        return f"Cannot read {file}: {e}"
    return path, content


def _apply_edit(
    repo: Path,
    file: str,
    old_content: str,
    new_content: str,
    tracker: "_ChangeTracker",
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
    if count == 0:
        total_lines = len(content.splitlines())
        region = find_best_match_region(content, old_content)
        return (
            f"old_content not found in {file} ({total_lines} lines). "
            f"The old_content must match the file EXACTLY, including whitespace "
            f"and indentation. Re-read the file with read_file and copy the exact "
            f"text you want to replace.\n\n{region}"
        )

    if count > 1:
        return f"old_content matches {count} locations in {file}. Provide more context to make it unique."

    new_file_content = content.replace(old_content, new_content, 1)
    path.write_text(new_file_content)
    tracker.modified.add(file)
    tracker.record_read(repo, file)

    new_lines = new_file_content.splitlines()
    edit_start = content[: content.index(old_content)].count("\n")
    edit_end = edit_start + new_content.count("\n")
    edit_center = (edit_start + edit_end) // 2
    context_window = numbered_window(new_lines, edit_center)

    return f"Applied edit to {file}.\n\nCurrent state around edit:\n\n{context_window}"


def _create_file(
    repo: Path,
    file: str,
    content: str,
    tracker: "_ChangeTracker",
    ignore: list[str] | None = None,
) -> str:
    if is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be created."
    if is_write_protected(file):
        return f"Access denied: {file} is managed by Sigil and cannot be created."
    path = validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if path.exists() and file not in tracker.created:
        return f"File already exists: {file}. Use apply_edit to modify it."
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        tracker.created.add(file)
        tracker.record_read(repo, file)
        return f"Created {file}."
    except OSError as e:
        return f"Cannot create {file}: {e}"


async def _get_diff(repo: Path) -> str:
    rc, stdout, _ = await arun(["git", "diff"], cwd=repo, timeout=10)
    if rc == 0:
        return stdout.strip()
    return ""


async def _generate_summary_from_diff(
    diff: str,
    task_description: str,
    existing_summary: str | None,
    model: str,
) -> str:
    diff_truncated = diff[:8000]
    prompt = (
        "Summarize the following code change for a pull request description. "
        "Write a bulleted list covering: what problem this solves, key changes "
        "in each file (name functions and concrete behaviors), and how the new "
        "code integrates with the existing codebase.\n\n"
        f"Task: {task_description}\n\n"
        f"Agent's notes: {existing_summary or '(none)'}\n\n"
        f"Diff:\n```\n{diff_truncated}\n```\n\n"
        "Be specific. Name files, functions, and behaviors. "
        "Do NOT use markdown headers. Keep it under 300 words."
    )
    try:
        response = await acompletion(
            label="engineer:summary",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1000,
        )
        content = response.choices[0].message.content
        if content and len(content.strip()) >= MIN_SUMMARY_LENGTH:
            return content.strip()
    except (KeyError, IndexError, AttributeError) as e:
        log.warning("Summary generation failed: %s", e)
    return existing_summary or ""


async def _run_command(repo: Path, cmd: str) -> tuple[bool, str]:
    rc, stdout, stderr = await arun(cmd, cwd=repo, timeout=COMMAND_TIMEOUT)
    output = (stdout + "\n" + stderr).strip()
    return rc == 0, output


async def _rollback(repo: Path, tracker: "_ChangeTracker") -> None:
    if tracker.modified:
        await arun(["git", "checkout", "--"] + list(tracker.modified), cwd=repo, timeout=10)

    for file in tracker.created:
        path = repo / file
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class _ChangeTracker:
    modified: set[str]
    created: set[str]
    last_read: dict[str, float]

    def __init__(self) -> None:
        self.modified = set()
        self.created = set()
        self.last_read = {}
        self.read_keys: dict[str, int] = {}
        self.read_totals: dict[str, int] = {}

    def reset_read_counters(self) -> None:
        self.read_keys.clear()
        self.read_totals.clear()
        self.last_read.clear()

    def record_read(self, repo: Path, file: str) -> None:
        try:
            self.last_read[file] = (repo / file).stat().st_mtime
        except OSError:
            self.last_read[file] = time.time()

    def check_staleness(self, repo: Path, file: str) -> str | None:
        if file not in self.last_read:
            return (
                f"You must read {file} before editing it. Use read_file first, "
                f"then use the EXACT content from that read as your old_content."
            )
        path = repo / file
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if mtime != self.last_read[file]:
            self.last_read.pop(file, None)
            return (
                f"{file} has been modified since you last read it. "
                f"Re-read the file with read_file before editing."
            )
        return None


def _executor_truncation_handler(messages: list[dict], choice: object, count: int) -> bool:
    max_consecutive = 3
    log.debug(
        "Executor output truncated (finish_reason=length) — %d/%d consecutive",
        count,
        max_consecutive,
    )
    if count >= max_consecutive:
        log.warning(
            "Model output cap too small — %d consecutive truncations, aborting",
            count,
        )
        return False
    content = getattr(choice, "message", None)
    if content and getattr(content, "content", None):
        messages.append(content)
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your response was truncated. Please continue exactly where you left off. "
                    "Do not repeat previous work — just continue with your next tool call."
                ),
            }
        )
    return True


def _make_read_handler(
    repo: Path,
    on_status: StatusCallback | None,
    ignore: list[str] | None,
    tracker: "_ChangeTracker | None" = None,
) -> Callable[[dict], Awaitable[ToolResult]]:

    async def _handler(args: dict) -> ToolResult:
        file = str(args.get("file", ""))
        if on_status:
            on_status(f"Reading {file}...")

        offset, limit = _coerce_read_args(args)
        key = f"{file}:{offset}"

        if tracker is not None:
            key_count = tracker.read_keys.get(key, 0)
            tracker.read_keys[key] = key_count + 1
            file_total = tracker.read_totals.get(file, 0)
            tracker.read_totals[file] = file_total + 1
        else:
            key_count = 0
            file_total = 0

        needs_reread = tracker is not None and file not in tracker.last_read

        if file_total >= MAX_READS_HARD_STOP:
            return ToolResult(
                content=(
                    f"HARD STOP: You have read {file} too many times. "
                    f"Aborting — call task_progress with what you have."
                ),
                stop=True,
                result=f"Aborted: stuck reading {file} repeatedly",
            )

        if key_count >= MAX_FULL_READS and not needs_reread:
            if tracker is None or file in tracker.modified:
                return ToolResult(
                    content=(
                        f"DOOM LOOP DETECTED: You are re-reading {file} at the same offset "
                        f"without making progress. STOP and re-think your approach.\n\n"
                        f"If apply_edit keeps failing with 'matches N locations', include MORE "
                        f"surrounding context in old_content to make it unique.\n\n"
                        f"If you cannot make progress, call task_progress to report what went wrong."
                    ),
                )

        result = _read_file(repo, file, offset=offset, limit=limit, ignore=ignore)
        if tracker is not None:
            tracker.record_read(repo, file)
        return ToolResult(content=result)

    return _handler


async def _summarize_hook_errors(raw_output: str, model: str) -> str:
    try:
        response = await acompletion(
            label="hook_summarizer",
            model=model,
            messages=[
                {"role": "user", "content": HOOK_SUMMARIZE_PROMPT.format(raw_output=raw_output)},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        summary = response.choices[0].message.content or ""
        if summary.strip():
            return summary.strip()
    except Exception as exc:
        log.debug("Hook summarization failed, using raw output: %s", exc)
    return raw_output


def _make_executor_tools(
    repo: Path,
    tracker: _ChangeTracker,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
) -> list[Tool]:

    edit_failures: dict[str, int] = {}
    MAX_EDIT_FAILURES = 3

    async def _apply_edit_handler(args: dict) -> ToolResult:
        file = str(args.get("file", ""))
        if on_status:
            on_status(f"Editing {file}...")
        result = _apply_edit(
            repo,
            file,
            str(args.get("old_content", "")),
            str(args.get("new_content", "")),
            tracker,
            ignore=ignore,
        )
        if "Applied edit" in result:
            edit_failures.pop(file, None)
        elif "not found" in result or "matches" in result:
            count = edit_failures.get(file, 0) + 1
            edit_failures[file] = count
            if count >= MAX_EDIT_FAILURES:
                edit_failures[file] = 0
                result += (
                    f"\n\nYou have failed to edit {file} {count} times in a row. "
                    f"STOP trying the same approach. You MUST re-read the file with "
                    f"read_file before your next apply_edit call on this file."
                )
        return ToolResult(content=result)

    async def _create_file_handler(args: dict) -> ToolResult:
        if on_status:
            on_status(f"Creating {args.get('file', '')}...")
        result = _create_file(
            repo,
            str(args.get("file", "")),
            fix_double_escaped(str(args.get("content", ""))),
            tracker,
            ignore=ignore,
        )
        return ToolResult(content=result)

    last_progress_snapshot: tuple[frozenset[str], frozenset[str]] | None = None

    async def _task_progress_handler(args: dict) -> ToolResult:
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

    async def _multi_edit_handler(args: dict) -> ToolResult:
        file = str(args.get("file", ""))
        edits = args.get("edits", [])
        if on_status:
            on_status(f"Multi-editing {file}...")

        if not isinstance(edits, list) or not edits:
            return ToolResult(content="edits must be a non-empty list.")

        vr = _validated_read(repo, file, tracker, ignore)
        if isinstance(vr, str):
            return ToolResult(content=vr)
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
                failed.append(f"Edit {i}: old_content matches {content.count(old)} locations")
                continue
            content = content.replace(old, new, 1)
            applied += 1

        if applied > 0:
            path.write_text(content)
            tracker.modified.add(file)
            tracker.record_read(repo, file)

        parts = [f"Applied {applied}/{len(edits)} edits to {file}."]
        if failed:
            parts.append("Failed edits:\n" + "\n".join(f"  - {f}" for f in failed))
        parts.append(f"\nFile now has {len(content.splitlines())} lines.")
        return ToolResult(content="\n".join(parts))

    return [
        make_read_file_tool(
            repo,
            on_status,
            ignore,
            handler=_make_read_handler(repo, on_status, ignore, tracker),
        ),
        Tool(
            name="apply_edit",
            description=(
                "Apply a code edit to a file. Provide the exact content to find and "
                "the content to replace it with. Call once per edit."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the file to edit, relative to the repo root.",
                    },
                    "old_content": {
                        "type": "string",
                        "description": (
                            "Exact content to find in the file. Must match precisely, "
                            "including whitespace and indentation."
                        ),
                    },
                    "new_content": {
                        "type": "string",
                        "description": "Content to replace old_content with.",
                    },
                },
                "required": ["file", "old_content", "new_content"],
            },
            handler=_apply_edit_handler,
            mutating=True,
        ),
        Tool(
            name="multi_edit",
            description=(
                "Apply multiple sequential edits to a SINGLE file atomically. "
                "Each edit is a find-and-replace pair. Earlier edits transform "
                "the file content for later edits. Use this when you need to "
                "make several changes to the same file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the file to edit, relative to the repo root.",
                    },
                    "edits": {
                        "type": "array",
                        "description": "List of edits to apply sequentially.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_content": {
                                    "type": "string",
                                    "description": "Exact content to find.",
                                },
                                "new_content": {
                                    "type": "string",
                                    "description": "Content to replace with.",
                                },
                            },
                            "required": ["old_content", "new_content"],
                        },
                    },
                },
                "required": ["file", "edits"],
            },
            handler=_multi_edit_handler,
            mutating=True,
        ),
        Tool(
            name="create_file",
            description="Create a new file with the given content.",
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path to the file to create, relative to the repo root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content for the new file.",
                    },
                },
                "required": ["file", "content"],
            },
            handler=_create_file_handler,
            mutating=True,
        ),
        make_grep_tool(repo, on_status),
        make_list_dir_tool(repo, ignore),
        Tool(
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
            handler=_task_progress_handler,
        ),
    ]


def _prepare_diff_for_review(diff: str, tracker: _ChangeTracker) -> str:
    file_diffs: list[tuple[str, str]] = []
    current_file = ""
    current_lines: list[str] = []

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if current_file and current_lines:
                file_diffs.append((current_file, "".join(current_lines)))
            current_lines = [line]
            parts = line.split()
            current_file = parts[3].removeprefix("b/") if len(parts) >= 4 else "unknown"
        else:
            current_lines.append(line)

    if current_file and current_lines:
        file_diffs.append((current_file, "".join(current_lines)))

    def _sort_key(item: tuple[str, str]) -> tuple[int, int]:
        name, content = item
        is_new = name in tracker.created
        return (0 if is_new else 1, len(content))

    file_diffs.sort(key=_sort_key)

    result_parts: list[str] = []
    total = 0
    included = 0

    for name, content in file_diffs:
        if total >= DIFF_TOTAL_CAP:
            remaining = len(file_diffs) - included
            if remaining > 0:
                result_parts.append(f"\n[{remaining} more file(s) omitted for brevity]")
            break
        budget = min(DIFF_PER_FILE_CAP, DIFF_TOTAL_CAP - total)
        if len(content) > budget:
            content = content[:budget] + f"\n[...truncated, {len(content)} chars total]"
        result_parts.append(content)
        total += len(content)
        included += 1

    return "".join(result_parts)


async def _run_architect(
    repo: Path,
    config: Config,
    task_description: str,
    memory_context: str,
    working_memory: str,
    repo_conventions: str,
    preloaded_files: str = "",
    ignore: list[str] | None = None,
    on_status: StatusCallback | None = None,
) -> str | None:
    architect_model = config.model_for("architect")

    plan_result: dict[str, str] = {"plan": ""}

    async def _submit_plan_handler(args: dict) -> ToolResult:
        plan_result["plan"] = str(args.get("plan", ""))
        return ToolResult(
            content="Plan submitted.",
            stop=True,
            result=plan_result["plan"],
        )

    tools = [
        make_read_file_tool(repo, on_status, ignore),
        make_grep_tool(repo, on_status),
        make_list_dir_tool(repo, ignore),
        Tool(
            name="submit_plan",
            description="Submit the implementation plan for the engineer to execute.",
            parameters={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "string",
                        "description": (
                            "A detailed implementation plan in markdown. Must include: "
                            "files to modify (with specific changes), files to create, "
                            "integration points, test strategy, and key design decisions."
                        ),
                    },
                },
                "required": ["plan"],
            },
            handler=_submit_plan_handler,
        ),
    ]

    repo_tree = list_directory(repo, ".", depth=3, ignore=ignore)

    context = ARCHITECT_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_memory or "(no prior runs)",
        repo_tree=repo_tree,
        preloaded_files_section=f"\n{preloaded_files}\n" if preloaded_files else "",
        task_description=task_description,
    )

    agent = Agent(
        label="architect",
        model=architect_model,
        tools=tools,
        system_prompt=ARCHITECT_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
        max_rounds=min(config.max_tool_calls, 10),
        max_tokens=config.max_tokens_for("architect") or 16_384,
        forced_final_tool="submit_plan",
    )

    result = await agent.run(
        messages=[{"role": "user", "content": context}],
        on_status=on_status,
    )

    if result.stop_result:
        return result.stop_result

    if plan_result["plan"]:
        return plan_result["plan"]

    if result.last_content and len(result.last_content.strip()) > 100:
        log.warning("Architect did not call submit_plan — using last text response as plan")
        return result.last_content.strip()

    return None


async def execute(
    repo: Path,
    config: Config,
    item: WorkItem,
    *,
    source_repo: Path | None = None,
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> tuple[ExecutionResult, _ChangeTracker]:
    task_desc = _describe_item(item)
    tracker = _ChangeTracker()

    task_knowledge_desc = f"Implement code change: {task_desc[:200]}"
    if on_status:
        on_status("Selecting relevant knowledge...")
    engineer_model = config.model_for("engineer")
    try:
        memory_files = await select_memory(
            repo,
            config.model_for("selector"),
            task_knowledge_desc,
            max_tokens=config.max_tokens_for("selector"),
        )
    except Exception as exc:
        log.warning("Knowledge selection failed: %s — proceeding without knowledge", exc)
        memory_files = {}
    memory_context = ""
    if memory_files:
        parts = []
        for name, content in memory_files.items():
            parts.append(f"### {name}\n{content}")
        memory_context = "\n\n".join(parts)

    working_md = load_working(source_repo or repo)

    repo_conventions = "(none detected)"
    if instructions and instructions.has_instructions:
        repo_conventions = instructions.format_for_prompt()

    preloaded = _preload_relevant_files(repo, item, ignore=config.ignore, tracker=tracker)

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, engineer_model)

    context_prompt = EXECUTOR_CONTEXT_PROMPT.format(
        memory_context=memory_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        mcp_tools_section=mcp_prompt,
        preloaded_files_section=f"\n{preloaded}\n" if preloaded else "",
    )

    attempt_history = ""
    fp = item_fingerprint(item)
    prior = read_attempts(source_repo or repo, item_id=fp)
    if prior:
        attempt_history = format_attempt_history(prior)

    task_suffix = ""
    if attempt_history:
        task_suffix = f"\n\n## Prior Attempts\n\n{attempt_history}"

    for hook in config.pre_hooks:
        if on_status:
            on_status(f"Running pre-hook: {hook}...")
        ok, output = await _run_command(repo, hook)
        if not ok:
            return (
                ExecutionResult(
                    success=False,
                    diff="",
                    hooks_passed=False,
                    failed_hook=hook,
                    retries=0,
                    failure_reason=f"Pre-hook failed: {hook}",
                    failure_type=FailureType.PRE_HOOK,
                ),
                tracker,
            )

    architect_plan: str | None = None
    architect_configured = bool(config.model_for("architect"))
    if architect_configured:
        if on_status:
            on_status("Architect planning...")
        architect_plan = await _run_architect(
            repo,
            config,
            task_desc + task_suffix,
            memory_context,
            working_md or "",
            repo_conventions,
            preloaded_files=preloaded,
            ignore=config.ignore,
            on_status=on_status,
        )

    if architect_plan:
        if on_status:
            preview = architect_plan[:200].replace("\n", " ")
            on_status(f"Architect plan: {preview}...")
        log.info("Architect plan for %s:\n%s", task_desc[:80], architect_plan)
        task_prompt = EXECUTOR_TASK_PROMPT_WITH_PLAN.format(
            task_description=task_desc + task_suffix,
            plan=architect_plan,
        )
    else:
        if architect_configured and on_status:
            on_status("Architect produced no plan — engineer will explore independently")
        task_prompt = EXECUTOR_TASK_PROMPT.format(task_description=task_desc) + task_suffix

    messages: list[dict] = [_build_cached_message(engineer_model, context_prompt, task_prompt)]

    ignore = config.ignore or None
    executor_tools = _make_executor_tools(repo, tracker, on_status, ignore=ignore)
    extra_schemas = extra_builtins + initial_mcp_tools

    engineer_agent = Agent(
        label="engineer",
        model=engineer_model,
        tools=executor_tools,
        system_prompt=ENGINEER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
        max_rounds=config.max_tool_calls,
        max_tokens=config.max_tokens_for("engineer") or 32_768,
        on_truncation=_executor_truncation_handler,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_schemas,
    )

    coord = AgentCoordinator(max_rounds=config.effective_max_retries + 1)
    coord.add_agent("engineer", engineer_agent, messages)

    done_summary: str | None = None
    doom_loop = False

    if on_status:
        on_status("Running engineer agent...")
    engineer_result = await coord.run_agent("engineer", on_status=on_status)

    if engineer_result.doom_loop:
        doom_loop = True
        log.warning("Doom loop detected in engineer agent — stopping execution")

    retries = 0
    max_rounds = config.effective_max_retries + 1
    hooks_ok = True
    errors: list[str] = []

    for round_num in range(max_rounds):
        if doom_loop:
            break
        hooks_ok = True
        failed_hook_name: str | None = None
        hook_results: list[tuple[str, str]] = []

        diff = await _get_diff(repo)
        if not diff:
            break

        for hook in config.post_hooks:
            if on_status:
                on_status(f"Running post-hook: {hook}...")
            ok, output = await _run_command(repo, hook)
            if not ok:
                hooks_ok = False
                if failed_hook_name is None:
                    failed_hook_name = hook
                hook_results.append((hook, output))

        per_hook_budget = OUTPUT_TRUNCATE_CHARS // max(len(hook_results), 1)
        errors = []
        for hook, output in hook_results:
            truncated = output[-per_hook_budget:] if len(output) > per_hook_budget else output
            errors.append(f"Hook `{hook}` failed:\n```\n{truncated}\n```")

        if hooks_ok or doom_loop:
            break

        if not hooks_ok:
            retries += 1
            if round_num >= max_rounds - 1:
                diff = await _get_diff(repo)
                last_error = errors[-1] if errors else ""
                return (
                    ExecutionResult(
                        success=False,
                        diff=diff,
                        hooks_passed=False,
                        failed_hook=failed_hook_name,
                        retries=retries,
                        failure_reason=f"Post-hooks failed after all retries.\n{last_error}",
                        failure_type=FailureType.POST_HOOK,
                    ),
                    tracker,
                )

            error_block = "\n\n".join(errors)
            if on_status:
                on_status(f"Post-hooks failed, fixing (retry {retries}/{max_rounds})...")
            summarizer_model = config.model_for("engineer")
            error_block = await _summarize_hook_errors(error_block, summarizer_model)

            tracker.reset_read_counters()
            inject = HOOK_FIX_INJECT_PROMPT.format(error_block=error_block)
            coord.inject("engineer", {"role": "user", "content": inject})
            engineer_result = await coord.run_agent("engineer", on_status=on_status)
            if engineer_result.doom_loop:
                doom_loop = True
            continue

    diff = await _get_diff(repo)
    success = hooks_ok and bool(diff)

    if success and not doom_loop:
        done_summary = engineer_result.stop_result
        if diff and (not done_summary or len(done_summary.strip()) < MIN_SUMMARY_LENGTH):
            done_summary = await _generate_summary_from_diff(
                diff, task_desc, done_summary, engineer_model
            )
        return (
            ExecutionResult(
                success=True,
                diff=diff,
                hooks_passed=True,
                failed_hook=None,
                retries=retries,
                failure_reason=None,
                summary=done_summary or "",
            ),
            tracker,
        )

    failure_reason = None
    failure_type: FailureType | None = None
    if doom_loop:
        failure_reason = "Doom loop detected — agent repeated actions without progress."
        failure_type = FailureType.DOOM_LOOP
    elif not diff:
        failure_reason = "No changes were made."
        failure_type = FailureType.NO_CHANGES
    elif not hooks_ok:
        last_error = errors[-1] if errors else ""
        failure_reason = f"Post-hooks failed after all retries.\n{last_error}"
        failure_type = FailureType.POST_HOOK

    if not diff:
        await _rollback(repo, tracker)

    diff = await _get_diff(repo)
    return (
        ExecutionResult(
            success=False,
            diff=diff,
            hooks_passed=hooks_ok,
            failed_hook=None,
            retries=retries,
            failure_reason=failure_reason,
            failure_type=failure_type,
            doom_loop_detected=doom_loop,
        ),
        tracker,
    )


async def _commit_changes(
    worktree_path: Path, item: WorkItem, tracker: _ChangeTracker
) -> tuple[bool, str]:
    rc, stdout, _ = await arun(["git", "status", "--porcelain"], cwd=worktree_path, timeout=10)
    if rc != 0 or not stdout.strip():
        return False, "No files to commit"

    rc, _, stderr = await arun(["git", "add", "-A"], cwd=worktree_path, timeout=30)
    if rc != 0:
        return False, f"Commit failed: git add failed: {stderr.strip()}"

    if isinstance(item, Finding):
        msg = f"sigil: fix {item.category} in {item.file}"
    else:
        msg = f"sigil: implement {item.title}"

    rc, _, stderr = await arun(["git", "commit", "-m", msg], cwd=worktree_path, timeout=30)
    if rc != 0:
        return False, f"Commit failed: {stderr.strip()}"
    return True, ""


async def _rebase_onto_main(repo: Path, worktree_path: Path) -> tuple[bool, str]:
    stashed = False
    rc_status, status_out, _ = await arun(
        ["git", "status", "--porcelain"], cwd=worktree_path, timeout=10
    )
    if rc_status == 0 and status_out.strip():
        rc_stash, _, _ = await arun(
            ["git", "stash", "--include-untracked"], cwd=worktree_path, timeout=30
        )
        stashed = rc_stash == 0

    rc, _, stderr = await arun(["git", "rebase", "main"], cwd=worktree_path, timeout=60)
    if rc == 0:
        if stashed:
            await arun(["git", "stash", "pop"], cwd=worktree_path, timeout=30)
        return True, ""

    rc, stdout, _ = await arun(
        ["git", "diff", "--name-only", "--diff-filter=U"], cwd=worktree_path, timeout=10
    )
    conflicted = [f for f in stdout.strip().splitlines() if f]

    memory_prefix = ".sigil/memory/"
    if conflicted and all(f.startswith(memory_prefix) for f in conflicted):
        for f in conflicted:
            await arun(["git", "checkout", "--ours", f], cwd=worktree_path, timeout=10)
            await arun(["git", "add", f], cwd=worktree_path, timeout=10)
        rc, _, _ = await arun(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd=worktree_path,
            timeout=60,
        )
        if rc == 0:
            if stashed:
                await arun(["git", "stash", "pop"], cwd=worktree_path, timeout=30)
            return True, ""

    await arun(["git", "rebase", "--abort"], cwd=worktree_path, timeout=10)
    if stashed:
        await arun(["git", "stash", "pop"], cwd=worktree_path, timeout=30)
    if conflicted:
        conflict_files = ", ".join(conflicted[:5])
        return False, f"Rebase conflict in {conflict_files}"
    return False, f"Rebase failed: {stderr.strip()}"


def _branch_name(slug: str) -> str:
    return f"sigil/auto/{slug}-{int(time.time())}"


async def _create_worktree(repo: Path, slug: str) -> tuple[Path, str]:
    branch = _branch_name(slug)
    worktree_path = repo / WORKTREE_DIR / slug
    if worktree_path.exists():
        await arun(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=repo,
            timeout=30,
        )
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    rc, _, stderr = await arun(
        ["git", "worktree", "add", str(worktree_path), "-b", branch],
        cwd=repo,
        timeout=30,
    )
    if rc != 0:
        raise OSError(f"Worktree creation failed: {stderr.strip()}")
    memory_src = repo / ".sigil" / "memory"
    if memory_src.exists():
        memory_dst = worktree_path / ".sigil" / "memory"
        memory_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(memory_src, memory_dst, dirs_exist_ok=True)
    return worktree_path, branch


async def _execute_in_worktree(
    repo: Path,
    config: Config,
    item: WorkItem,
    slug: str,
    *,
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> tuple[WorkItem, ExecutionResult, str]:
    try:
        worktree_path, branch = await _create_worktree(repo, slug)
    except OSError as e:
        return (
            item,
            ExecutionResult(
                success=False,
                diff="",
                hooks_passed=False,
                failed_hook=None,
                retries=0,
                failure_reason=f"Worktree creation failed: {e}",
                failure_type=FailureType.WORKTREE,
                downgraded=True,
                downgrade_context=f"Worktree creation failed: {e}",
            ),
            "",
        )
    token = set_trace_task(slug)
    try:
        return await _finalize_worktree(
            repo,
            worktree_path,
            config,
            item,
            slug,
            branch,
            instructions=instructions,
            mcp_mgr=mcp_mgr,
            on_status=on_status,
        )
    finally:
        reset_trace_task(token)


async def _finalize_worktree(
    repo: Path,
    worktree_path: Path,
    config: Config,
    item: WorkItem,
    slug: str,
    branch: str,
    *,
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> tuple[WorkItem, ExecutionResult, str]:
    result, tracker = await execute(
        worktree_path,
        config,
        item,
        source_repo=repo,
        instructions=instructions,
        mcp_mgr=mcp_mgr,
        on_status=on_status,
    )

    if not result.success:
        desc = _describe_item(item)
        committed = False
        if result.diff:
            committed, commit_err = await _commit_changes(worktree_path, item, tracker)
            if not committed:
                log.warning("Downgrade commit failed for %s: %s", slug, commit_err)
        return (
            item,
            ExecutionResult(
                success=False,
                diff=result.diff if committed else "",
                hooks_passed=result.hooks_passed,
                failed_hook=result.failed_hook,
                retries=result.retries,
                failure_reason=result.failure_reason,
                failure_type=result.failure_type,
                doom_loop_detected=result.doom_loop_detected,
                downgraded=True,
                downgrade_context=(
                    f"Execution failed after {result.retries} retries.\n"
                    f"Reason: {result.failure_reason}\n"
                    f"Task: {desc[:500]}"
                ),
            ),
            branch,
        )

    commit_ok, commit_err = await _commit_changes(worktree_path, item, tracker)
    if not commit_ok:
        return (
            item,
            ExecutionResult(
                success=False,
                diff=result.diff,
                hooks_passed=result.hooks_passed,
                failed_hook=result.failed_hook,
                retries=result.retries,
                failure_reason=f"Commit failed: {commit_err}",
                failure_type=FailureType.COMMIT,
                doom_loop_detected=result.doom_loop_detected,
                downgraded=True,
                downgrade_context=f"Changes were made but commit failed: {commit_err}",
            ),
            branch,
        )

    rebase_ok, rebase_err = await _rebase_onto_main(repo, worktree_path)
    if not rebase_ok:
        desc = _describe_item(item)
        return (
            item,
            ExecutionResult(
                success=False,
                diff=result.diff,
                hooks_passed=result.hooks_passed,
                failed_hook=result.failed_hook,
                retries=result.retries,
                failure_reason=f"Rebase conflict: {rebase_err}",
                failure_type=FailureType.REBASE,
                doom_loop_detected=result.doom_loop_detected,
                downgraded=True,
                downgrade_context=(
                    f"Changes were implemented and committed but rebase onto main failed.\n"
                    f"Conflict: {rebase_err}\n"
                    f"Task: {desc[:500]}"
                ),
            ),
            branch,
        )

    return item, result, branch


def _dedup_slugs(items: list[WorkItem]) -> list[str]:
    seen: dict[str, int] = {}
    slugs: list[str] = []
    for item in items:
        base = slugify(item)
        count = seen.get(base, 0)
        seen[base] = count + 1
        slugs.append(f"{base}-{count}" if count else base)
    return slugs


async def _cleanup_worktree(repo: Path, worktree_path: Path, branch: str) -> None:
    await arun(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo, timeout=30)
    await arun(["git", "branch", "-D", branch], cwd=repo, timeout=10)


async def execute_parallel(
    repo: Path,
    config: Config,
    items: list[WorkItem],
    *,
    run_id: str = "",
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
    on_item_status: ItemStatusCallback | None = None,
    on_item_done: ItemDoneCallback | None = None,
) -> list[tuple[WorkItem, ExecutionResult, str]]:
    if not items:
        return []

    slugs = _dedup_slugs(items)
    sem = asyncio.Semaphore(config.max_parallel_agents)
    engineer_model = config.model_for("engineer")

    def _item_callback(slug: str) -> StatusCallback | None:
        if on_item_status is not None:
            return lambda msg, _slug=slug: on_item_status(_slug, msg)
        if on_status is None:
            return None
        return lambda msg, _slug=slug: on_status(f"[{_slug}] {msg}")

    async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
        if on_item_status is not None:
            on_item_status(slug, "Waiting for slot...")
        async with sem:
            if on_item_status is not None:
                on_item_status(slug, "Starting...")
            _, tok_before, _ = get_usage_snapshot()
            t0 = time.monotonic()
            result_tuple = await _execute_in_worktree(
                repo,
                config,
                item,
                slug,
                instructions=instructions,
                mcp_mgr=mcp_mgr,
                on_status=_item_callback(slug),
            )
            duration = time.monotonic() - t0
            _, tok_after, _ = get_usage_snapshot()
            if on_item_done is not None:
                _, exec_result_inner, _ = result_tuple
                on_item_done(slug, exec_result_inner.success)

            _, exec_result, _ = result_tuple
            outcome = (
                "success"
                if exec_result.success
                else (exec_result.failure_type.value if exec_result.failure_type else "unknown")
            )
            item_type = "finding" if isinstance(item, Finding) else "idea"
            category = item.category if isinstance(item, Finding) else ""
            complexity = item.complexity if isinstance(item, FeatureIdea) else ""

            record = AttemptRecord(
                run_id=run_id,
                timestamp=now_utc(),
                item_type=item_type,
                item_id=item_fingerprint(item),
                category=category,
                complexity=complexity,
                approach=_describe_item(item)[:300],
                model=engineer_model,
                retries=exec_result.retries,
                outcome=outcome,
                tokens_used=tok_after - tok_before,
                duration_s=round(duration, 1),
                failure_detail=exec_result.failure_reason or "",
            )
            try:
                log_attempt(repo, record)
            except OSError:
                log.warning("Failed to write attempt log")

            return result_tuple

    results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))

    for slug, (_, result, branch) in zip(slugs, results):
        if not branch:
            continue
        worktree_path = repo / WORKTREE_DIR / slug
        if not result.success and not result.diff:
            await _cleanup_worktree(repo, worktree_path, branch)

    return results
