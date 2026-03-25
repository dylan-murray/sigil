import asyncio
import logging
import shutil
import time
from fnmatch import fnmatch
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sigil.core.agent import Agent, AgentCoordinator, Tool, ToolResult
from sigil.core.instructions import Instructions
from sigil.state.attempts import AttemptRecord, format_attempt_history, log_attempt, read_attempts
from sigil.state.chronic import WorkItem, fingerprint as item_fingerprint, slugify
from sigil.core.config import Config
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.knowledge import select_knowledge
from sigil.core.llm import (
    acompletion,
    get_usage_snapshot,
    supports_prompt_caching,
)
from sigil.pipeline.maintenance import Finding
from sigil.core.mcp import MCPManager, prepare_mcp_for_agent
from sigil.state.memory import load_working
from sigil.core.utils import StatusCallback, arun, now_utc

log = logging.getLogger(__name__)


class FailureType(str, Enum):
    PRE_HOOK = "pre_hook"
    POST_HOOK = "post_hook"
    NO_CHANGES = "no_changes"
    DOOM_LOOP = "doom_loop"
    WORKTREE = "worktree"
    COMMIT = "commit"
    REBASE = "rebase"


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    diff: str
    hooks_passed: bool
    failed_hook: str | None
    retries: int
    failure_reason: str | None
    failure_type: FailureType | None = None
    doom_loop_detected: bool = False
    summary: str = ""
    downgraded: bool = False
    downgrade_context: str = ""


APPLY_EDIT_TOOL = {
    "type": "function",
    "function": {
        "name": "apply_edit",
        "description": (
            "Apply a code edit to a file. Provide the exact content to find and "
            "the content to replace it with. Call once per edit."
        ),
        "parameters": {
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
    },
}

CREATE_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_file",
        "description": "Create a new file with the given content.",
        "parameters": {
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
    },
}

DONE_TOOL = {
    "type": "function",
    "function": {
        "name": "done",
        "description": "Signal that all code changes are complete. The summary becomes the 'Changes' section of the PR description and is read by human reviewers.",
        "parameters": {
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
    },
}

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read the contents of a file in the repository. Use this to inspect "
            "files you need to understand before making edits. "
            "Large files are truncated — use offset to read further."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Path to the file to read, relative to the repo root.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, default 1). Must be a single integer, NOT a list or range. To read lines 300-420, use offset=300 and limit=120.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default 2000). Must be a single integer, NOT a list or range. Use with offset to read a specific range.",
                },
            },
            "required": ["file"],
        },
    },
}

EXECUTOR_TOOLS = [READ_FILE_TOOL, APPLY_EDIT_TOOL, CREATE_FILE_TOOL, DONE_TOOL]

COMMAND_TIMEOUT = 120
OUTPUT_TRUNCATE_CHARS = 4000
MAX_READ_LINES = 2000
MAX_READ_BYTES = 50_000
MIN_SUMMARY_LENGTH = 200

ENGINEER_SYSTEM_PROMPT = """\
You are a staff software engineer at one of the best engineering organizations
in the world. Your job is to implement a complete, production-quality code
change in a repository. This will be opened as a pull request and reviewed by
your peers — write code you'd be proud to put your name on.

## Repository Conventions

These are the repo's coding conventions. Follow them exactly — they are the
source of truth for this repository:

{repo_conventions}

## Workflow

1. **Explore**: Read the files you need to understand before making any edit.
   Read the target file, related files (callers, sibling modules), and existing
   tests so you understand the full context.
2. **Plan**: Identify every file that needs modification. Think about edge cases
   and how the change integrates with existing code.
3. **Implement**: Use apply_edit for surgical edits and create_file for new files.
   Type-hint all function parameters and return types.
4. **Verify**: Before calling done, check your work:
   - Are all imports correct and minimal?
   - Does new code integrate with existing callers/consumers?
   - If you created a new module, is it wired in (imports, config, CLI)?
   Call done only when you are confident the change is complete and correct.

## Rules

- Read before you edit — always understand context first
- Follow the repo's coding conventions EXACTLY (imports, types, naming, style)
- Use only libraries already present in the project's dependencies
- Do not add comments unless the logic is non-obvious
- Do not refactor unrelated code
- NEVER modify files under .sigil/ — memory, config, and ideas are managed separately
- Make the change complete — no TODOs, no placeholders, no stub implementations
- If you create a new module, wire it into the rest of the codebase (imports,
  CLI registration, config, etc.) — dead code is worse than no code
- Prefer small, focused functions over large ones
- Handle errors explicitly — no bare except, no silent failures
"""

EXECUTOR_CONTEXT_PROMPT = """\
## Project Context

{knowledge_context}

## Working Memory

{working_memory}
{mcp_tools_section}
"""

EXECUTOR_TASK_PROMPT = """\
Here is the task:

{task_description}
"""


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


SENSITIVE_FILE_NAMES: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.development",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".bash_logout",
    ".bash_history",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".zlogin",
    ".zlogout",
    ".zsh_history",
    ".profile",
    ".login",
    ".cshrc",
    ".tcshrc",
    ".kshrc",
    ".fishrc",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".pgpass",
    ".my.cnf",
    ".docker/config.json",
    ".aws/credentials",
    ".aws/config",
    ".ssh/config",
    ".ssh/known_hosts",
    ".gitconfig",
    "credentials.json",
    "service-account.json",
    "service_account.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.toml",
    ".secrets",
    "token.json",
    "tokens.json",
    "keyfile.json",
    ".htpasswd",
}

SENSITIVE_FILE_EXTENSIONS: set[str] = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".crt",
    ".cer",
    ".der",
    ".pkcs12",
}

SENSITIVE_FILE_PREFIXES: tuple[str, ...] = (
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
)


WRITE_PROTECTED_PATHS: tuple[str, ...] = (".sigil/",)


def _is_sensitive_file(file: str) -> bool:
    name = Path(file).name
    if name in SENSITIVE_FILE_NAMES:
        return True
    normalized = file.replace("\\", "/")
    for part in normalized.split("/"):
        if part in SENSITIVE_FILE_NAMES:
            return True
    suffix = Path(file).suffix.lower()
    if suffix in SENSITIVE_FILE_EXTENSIONS:
        return True
    if name.startswith(SENSITIVE_FILE_PREFIXES):
        return True
    if name.startswith(".env."):
        return True
    return False


def _is_write_protected(file: str) -> bool:
    normalized = file.replace("\\", "/")
    return any(normalized.startswith(p) or f"/{p}" in normalized for p in WRITE_PROTECTED_PATHS)


def _validate_path(repo: Path, file: str, ignore: list[str] | None = None) -> Path | None:
    if _is_sensitive_file(file):
        return None
    if ignore and any(fnmatch(file, p) for p in ignore):
        return None
    try:
        resolved = (repo / file).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(repo.resolve()):
        return None
    return resolved


def _read_file(
    repo: Path,
    file: str,
    offset: int = 1,
    limit: int = MAX_READ_LINES,
    ignore: list[str] | None = None,
) -> str:
    if _is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be read."
    path = _validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if not path.exists():
        return f"File not found: {file}"
    if not path.is_file():
        return f"Not a file: {file}"
    try:
        all_lines = path.read_text().splitlines(keepends=True)
    except OSError as e:
        return f"Cannot read {file}: {e}"

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

    content = "".join(output_lines)
    lines_returned = len(output_lines)
    end_line = start + lines_returned

    if end_line < total_lines:
        if not content.endswith("\n"):
            content += "\n"
        content += (
            f"[truncated — {total_lines} lines total. "
            f"Use read_file with offset={end_line + 1} to continue.]"
        )

    return content


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


@dataclass
class _ChangeTracker:
    modified: set[str]
    created: set[str]

    def __init__(self) -> None:
        self.modified = set()
        self.created = set()


def _apply_edit(
    repo: Path,
    file: str,
    old_content: str,
    new_content: str,
    tracker: _ChangeTracker,
    ignore: list[str] | None = None,
) -> str:
    if _is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be modified."
    if _is_write_protected(file):
        return f"Access denied: {file} is managed by Sigil and cannot be modified."
    path = _validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if not path.exists():
        return f"File not found: {file}"
    try:
        content = path.read_text()
    except OSError as e:
        return f"Cannot read {file}: {e}"

    if old_content not in content:
        return f"old_content not found in {file}. Make sure it matches exactly."

    count = content.count(old_content)
    if count > 1:
        return f"old_content matches {count} locations in {file}. Provide more context to make it unique."

    path.write_text(content.replace(old_content, new_content, 1))
    tracker.modified.add(file)
    return f"Applied edit to {file}."


def _create_file(
    repo: Path,
    file: str,
    content: str,
    tracker: _ChangeTracker,
    ignore: list[str] | None = None,
) -> str:
    if _is_sensitive_file(file):
        return f"Access denied: {file} is a sensitive file and cannot be created."
    if _is_write_protected(file):
        return f"Access denied: {file} is managed by Sigil and cannot be created."
    path = _validate_path(repo, file, ignore=ignore)
    if path is None:
        return f"Access denied: {file} is outside the repository or ignored by config."
    if path.exists():
        return f"File already exists: {file}. Use apply_edit to modify it."
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        tracker.created.add(file)
        return f"Created {file}."
    except OSError as e:
        return f"Cannot create {file}: {e}"


async def _rollback(repo: Path, tracker: _ChangeTracker) -> None:
    if tracker.modified:
        await arun(["git", "checkout", "--"] + list(tracker.modified), cwd=repo, timeout=10)

    for file in tracker.created:
        path = repo / file
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


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


def _make_executor_tools(
    repo: Path,
    tracker: _ChangeTracker,
    on_status: StatusCallback | None,
    ignore: list[str] | None = None,
) -> list[Tool]:
    async def _read_file_handler(args: dict) -> ToolResult:
        if on_status:
            on_status(f"Reading {args.get('file', '')}...")
        raw_offset = args.get("offset", 1)
        raw_limit = args.get("limit", MAX_READ_LINES)
        if isinstance(raw_offset, list):
            raw_offset = raw_offset[0] if raw_offset else 1
        if isinstance(raw_limit, list):
            raw_limit = raw_limit[0] if raw_limit else MAX_READ_LINES
        result = _read_file(
            repo,
            str(args.get("file", "")),
            offset=int(raw_offset),
            limit=int(raw_limit),
            ignore=ignore,
        )
        return ToolResult(content=result)

    async def _apply_edit_handler(args: dict) -> ToolResult:
        if on_status:
            on_status(f"Editing {args.get('file', '')}...")
        result = _apply_edit(
            repo,
            str(args.get("file", "")),
            str(args.get("old_content", "")),
            str(args.get("new_content", "")),
            tracker,
            ignore=ignore,
        )
        return ToolResult(content=result)

    async def _create_file_handler(args: dict) -> ToolResult:
        if on_status:
            on_status(f"Creating {args.get('file', '')}...")
        result = _create_file(
            repo,
            str(args.get("file", "")),
            str(args.get("content", "")),
            tracker,
            ignore=ignore,
        )
        return ToolResult(content=result)

    async def _done_handler(args: dict) -> ToolResult:
        return ToolResult(
            content="Done acknowledged.",
            stop=True,
            result=args.get("summary"),
        )

    return [
        Tool(
            name=READ_FILE_TOOL["function"]["name"],
            description=READ_FILE_TOOL["function"]["description"],
            parameters=READ_FILE_TOOL["function"]["parameters"],
            handler=_read_file_handler,
        ),
        Tool(
            name=APPLY_EDIT_TOOL["function"]["name"],
            description=APPLY_EDIT_TOOL["function"]["description"],
            parameters=APPLY_EDIT_TOOL["function"]["parameters"],
            handler=_apply_edit_handler,
        ),
        Tool(
            name=CREATE_FILE_TOOL["function"]["name"],
            description=CREATE_FILE_TOOL["function"]["description"],
            parameters=CREATE_FILE_TOOL["function"]["parameters"],
            handler=_create_file_handler,
        ),
        Tool(
            name=DONE_TOOL["function"]["name"],
            description=DONE_TOOL["function"]["description"],
            parameters=DONE_TOOL["function"]["parameters"],
            handler=_done_handler,
        ),
    ]


DIFF_PER_FILE_CAP = 4000
DIFF_TOTAL_CAP = 15000


def _prepare_diff_for_qa(diff: str, tracker: _ChangeTracker) -> str:
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


QA_SYSTEM_PROMPT = """\
You are a staff-level QA engineer. A software engineer has just implemented
changes to a repository. Your job is to verify those changes are correct and
well-tested.

## Repository Conventions

{repo_conventions}

## Workflow

1. Read existing test files first — understand the test framework, fixtures,
   naming conventions, and import patterns before writing anything.
2. Write tests for the new code. You MUST create or modify at least one test
   file — never skip this step.
3. Fix bugs you find in the engineer's code (broken imports, incorrect logic,
   missing edge cases, type errors).
4. Call done with a summary of what you tested and what you fixed.

## Guardrails

- Do NOT implement new features — only write tests and fix bugs
- Follow the repo's coding conventions EXACTLY (imports, types, naming, style)
- Use only libraries already present in the project's dependencies
- Do not add comments unless the logic is non-obvious
- Do NOT modify files under .sigil/
- Your first action MUST be to call read_file on an existing test file
"""

QA_CONTEXT_PROMPT = """\
## Task Being Verified

{task_description}

## Project Context

{knowledge_context}

## Changes Made

Created: {created_files}
Modified: {modified_files}

```
{diff}
```

## Your Plan

1. Read an existing test file that is RELATED to the modified files above (look
   for tests/ files that match the module names). If none exist, read ANY test
   file to learn the project's test patterns.
2. Write or update tests that cover the new/changed behavior.
3. Fix any bugs you find in the engineer's code.
4. Call done with a summary.

Do NOT read the same file twice. If you already have the content, proceed to writing.
"""

QA_UPDATE_PROMPT = """\
Post-hooks failed. You must fix these failures before the PR can be opened.

## Original Task

{task_description}

## Current State

Created: {created_files}
Modified: {modified_files}

```
{diff}
```

Diagnose the root cause and fix it:
- Read the failing file around the error line
- Fix syntax errors, broken tests, lint violations, or import issues
- If a test you wrote is wrong, fix or remove it
- If existing tests broke, update them to match the new code
- Do NOT implement new features — only fix what's broken
- Call done when finished
"""

MAX_QA_TOOL_CALLS = 30


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
    knowledge_files = await select_knowledge(
        repo, config.model_for("selector"), task_knowledge_desc
    )
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    attempt_history = ""
    history_repo = source_repo or repo
    past = read_attempts(history_repo, item_id=item_fingerprint(item))
    if past:
        attempt_history = format_attempt_history(past)

    repo_conventions = "(none detected)"
    if instructions and instructions.has_instructions:
        repo_conventions = instructions.format_for_prompt()

    working_md = load_working(repo)

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, engineer_model)
    context_prompt = EXECUTOR_CONTEXT_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        working_memory=working_md or "(no prior runs)",
        mcp_tools_section=mcp_prompt,
    )
    task_suffix = ""
    if attempt_history:
        task_suffix = f"\n\n{attempt_history}\n\nAvoid approaches that failed before. Try a different strategy."
    task_prompt = EXECUTOR_TASK_PROMPT.format(task_description=task_desc) + task_suffix

    messages: list[dict] = [_build_cached_message(engineer_model, context_prompt, task_prompt)]
    all_tools: list[dict] = EXECUTOR_TOOLS + extra_builtins + initial_mcp_tools

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

    ignore = config.ignore or None
    executor_tools = _make_executor_tools(repo, tracker, on_status, ignore=ignore)
    executor_tool_names = {t.name for t in executor_tools}
    extra_schemas = [t for t in all_tools if t["function"]["name"] not in executor_tool_names]

    engineer_agent = Agent(
        label="engineer",
        model=engineer_model,
        tools=executor_tools,
        system_prompt=ENGINEER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
        max_rounds=config.max_tool_calls,
        agent_key="engineer",
        on_truncation=_executor_truncation_handler,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_schemas,
    )

    coord = AgentCoordinator(max_rounds=config.max_retries + 1)
    coord.add_agent("engineer", engineer_agent, messages)

    qa_model = config.model_for("qa")
    qa_initialized = False

    done_summary: str | None = None
    qa_summary: str | None = None
    doom_loop = False
    hooks_passed = True
    failed_hook: str | None = None
    retries = 0
    errors: list[str] = []

    if on_status:
        on_status("Running engineer agent...")
    engineer_result = await coord.run_agent("engineer", on_status=on_status)

    if engineer_result.doom_loop:
        doom_loop = True

    if engineer_result.stop_result is not None:
        done_summary = engineer_result.stop_result

    if not doom_loop and not done_summary:
        log.debug("Engineer exited without calling done — prompting for summary")
        coord.inject(
            "engineer",
            {
                "role": "user",
                "content": (
                    "You did not call the done tool. You MUST call done with a detailed summary "
                    "of all changes you made. Review your work and call done now."
                ),
            },
        )
        retry_result = await coord.run_agent("engineer", on_status=on_status)
        if retry_result.doom_loop:
            doom_loop = True
        if retry_result.stop_result is not None:
            done_summary = retry_result.stop_result

    for round_num in range(coord.max_rounds):
        if not doom_loop:
            current_diff = await _get_diff(repo)
            if current_diff:
                prepared_diff = _prepare_diff_for_qa(current_diff, tracker)
                created_str = ", ".join(sorted(tracker.created)) or "(none)"
                modified_str = ", ".join(sorted(tracker.modified)) or "(none)"

                if not qa_initialized:
                    if on_status:
                        on_status("Running QA agent...")
                    qa_agent = Agent(
                        label="qa",
                        model=qa_model,
                        tools=_make_executor_tools(repo, tracker, on_status),
                        system_prompt=QA_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
                        max_rounds=MAX_QA_TOOL_CALLS,
                        agent_key="qa",
                        on_truncation=_executor_truncation_handler,
                    )
                    qa_context = QA_CONTEXT_PROMPT.format(
                        task_description=task_desc,
                        knowledge_context=knowledge_context or "(no knowledge files yet)",
                        created_files=created_str,
                        modified_files=modified_str,
                        diff=prepared_diff,
                    )
                    qa_messages = [
                        {"role": "user", "content": qa_context},
                    ]
                    coord.add_agent("qa", qa_agent, qa_messages)
                    qa_initialized = True
                else:
                    if on_status:
                        on_status("QA agent fixing issues...")
                    coord.inject(
                        "qa",
                        {
                            "role": "user",
                            "content": QA_UPDATE_PROMPT.format(
                                task_description=task_desc,
                                diff=prepared_diff,
                                created_files=created_str,
                                modified_files=modified_str,
                            ),
                        },
                    )

                qa_result = await coord.run_agent("qa", on_status=on_status)
                if qa_result.doom_loop:
                    doom_loop = True
                if qa_result.stop_result is not None:
                    qa_summary = qa_result.stop_result

        hooks_passed = True
        failed_hook = None
        errors = []

        for hook in config.post_hooks:
            if on_status:
                on_status(f"Running post-hook: {hook}...")
            ok, output = await _run_command(repo, hook)
            if not ok:
                hooks_passed = False
                failed_hook = hook
                truncated = (
                    output[-OUTPUT_TRUNCATE_CHARS:]
                    if len(output) > OUTPUT_TRUNCATE_CHARS
                    else output
                )
                errors.append(f"Hook `{hook}` failed:\n```\n{truncated}\n```")
                break

        if hooks_passed or doom_loop:
            break

        if round_num < coord.max_rounds - 1 and qa_initialized:
            retries += 1
            error_block = "\n\n".join(errors)
            coord.inject(
                "qa",
                {
                    "role": "user",
                    "content": (
                        f"Post-hooks failed (attempt {round_num + 1}/{coord.max_rounds}). "
                        "You MUST fix these issues before the PR can be opened.\n\n"
                        f"Original task: {task_desc[:300]}\n\n"
                        f"{error_block}\n\n"
                        "Read the failing file around the error line, fix the root cause, "
                        "and call done."
                    ),
                },
            )

    if qa_summary and done_summary:
        done_summary += f"\n\nQA agent:\n{qa_summary}"
    elif qa_summary:
        done_summary = qa_summary

    diff = await _get_diff(repo)

    if (
        diff
        and (not done_summary or len(done_summary.strip()) < MIN_SUMMARY_LENGTH)
        and not doom_loop
    ):
        log.debug(
            "Generating summary from diff (executor summary was %s)",
            "missing" if not done_summary else f"too short: {len(done_summary.strip())} chars",
        )
        if on_status:
            on_status("Generating change summary...")
        done_summary = await _generate_summary_from_diff(
            diff, task_desc, done_summary, config.model_for("selector")
        )

    success = hooks_passed and bool(diff)

    failure_reason = None
    failure_type: FailureType | None = None
    if doom_loop and not success:
        failure_reason = "Doom loop detected — agent repeated actions without progress."
        failure_type = FailureType.DOOM_LOOP
    elif not diff:
        failure_reason = "No changes were made."
        failure_type = FailureType.NO_CHANGES
    elif not hooks_passed:
        last_error = errors[-1] if errors else ""
        failure_reason = f"Post-hooks failed after all retries.\n{last_error}"
        failure_type = FailureType.POST_HOOK

    if not diff:
        await _rollback(repo, tracker)

    return (
        ExecutionResult(
            success=success,
            diff=diff,
            hooks_passed=hooks_passed,
            failed_hook=failed_hook,
            retries=retries,
            failure_reason=failure_reason,
            failure_type=failure_type,
            doom_loop_detected=doom_loop,
            summary=done_summary or "",
        ),
        tracker,
    )


async def _commit_changes(
    worktree_path: Path, item: WorkItem, tracker: _ChangeTracker
) -> tuple[bool, str]:
    files_to_stage = sorted(tracker.modified | tracker.created)
    if not files_to_stage:
        return False, "No files to commit"

    rc, _, stderr = await arun(["git", "add", "--"] + files_to_stage, cwd=worktree_path, timeout=30)
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


WORKTREE_DIR = ".sigil/worktrees"


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
) -> list[tuple[WorkItem, ExecutionResult, str]]:
    if not items:
        return []

    slugs = _dedup_slugs(items)
    sem = asyncio.Semaphore(config.max_parallel_agents)
    engineer_model = config.model_for("engineer")

    def _item_callback(slug: str) -> StatusCallback | None:
        if on_status is None:
            return None
        return lambda msg, _slug=slug: on_status(f"[{_slug}] {msg}")

    async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
        async with sem:
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
