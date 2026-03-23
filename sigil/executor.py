import asyncio
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from sigil.agent_config import AgentConfigResult
from sigil.config import DEFAULT_CHEAP_MODEL, Config
from sigil.ideation import FeatureIdea
from sigil.knowledge import select_knowledge
from sigil.llm import (
    acompletion,
    compact_messages,
    detect_doom_loop,
    get_agent_output_cap,
    mask_old_tool_outputs,
    supports_prompt_caching,
)
from sigil.maintenance import Finding
from sigil.mcp import MCPManager, handle_search_tools_call, prepare_mcp_for_agent
from sigil.utils import StatusCallback, arun

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    diff: str
    hooks_passed: bool
    failed_hook: str | None
    retries: int
    failure_reason: str | None
    summary: str = ""
    downgraded: bool = False
    downgrade_context: str = ""


WorkItem = Union[Finding, FeatureIdea]

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
        "description": "Signal that all code changes are complete.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of changes made.",
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
                    "description": "Line number to start reading from (1-based, default 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default 2000).",
                },
            },
            "required": ["file"],
        },
    },
}

EXECUTOR_TOOLS = [READ_FILE_TOOL, APPLY_EDIT_TOOL, CREATE_FILE_TOOL, DONE_TOOL]

MAX_TOOL_CALLS_PER_PASS = 15
COMMAND_TIMEOUT = 120
OUTPUT_TRUNCATE_CHARS = 4000
MAX_READ_LINES = 2000
MAX_READ_BYTES = 50_000

EXECUTOR_CONTEXT_PROMPT = """\
You are Sigil, an autonomous code improvement agent. Your job is to implement
a specific code change in a repository.

Here is the project knowledge (architecture, patterns, conventions):

{knowledge_context}

Here are the repo's coding conventions from its agent config files (respect these):

{repo_conventions}

Use the read_file tool to inspect any files you need to understand before
making changes. Then use apply_edit to make surgical edits to existing files,
or create_file to create new files. Make the minimum change needed.

When you are done making all changes, call the done tool with a brief summary.
{mcp_tools_section}

Rules:
- Read files before editing them — understand context first
- Make the smallest change that correctly addresses the task
- Do not add comments unless the logic is non-obvious
- Preserve existing code style and conventions
- Only edit files that need to change
- Do not refactor unrelated code
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
        return (
            f"Category: {item.category}\n"
            f"Location: {loc}\n"
            f"Problem: {item.description}\n"
            f"Suggested fix: {item.suggested_fix}"
        )
    return f"Feature: {item.title}\nDescription: {item.description}\nComplexity: {item.complexity}"


def _validate_path(repo: Path, file: str) -> Path | None:
    try:
        resolved = (repo / file).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(repo.resolve()):
        return None
    return resolved


def _read_file(repo: Path, file: str, offset: int = 1, limit: int = MAX_READ_LINES) -> str:
    path = _validate_path(repo, file)
    if path is None:
        return f"Access denied: {file} is outside the repository."
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
    repo: Path, file: str, old_content: str, new_content: str, tracker: _ChangeTracker
) -> str:
    path = _validate_path(repo, file)
    if path is None:
        return f"Access denied: {file} is outside the repository."
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


def _create_file(repo: Path, file: str, content: str, tracker: _ChangeTracker) -> str:
    path = _validate_path(repo, file)
    if path is None:
        return f"Access denied: {file} is outside the repository."
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


async def _run_llm_edits(
    repo: Path,
    model: str,
    messages: list[dict],
    tracker: _ChangeTracker,
    all_tools: list[dict],
    *,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> str | None:

    for _ in range(MAX_TOOL_CALLS_PER_PASS):
        if detect_doom_loop(messages):
            log.warning("Doom loop detected in executor — breaking")
            break
        mask_old_tool_outputs(messages)
        await compact_messages(messages, DEFAULT_CHEAP_MODEL)
        if on_status:
            on_status("Generating...")
        response = await acompletion(
            label="execution",
            model=model,
            messages=messages,
            tools=all_tools,
            temperature=0.0,
            max_tokens=get_agent_output_cap("codegen", model),
        )

        choice = response.choices[0]

        if not choice.message.tool_calls:
            break

        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Invalid JSON arguments.",
                    }
                )
                continue

            if name == "read_file":
                if on_status:
                    on_status(f"Reading {args.get('file', '')}...")
                result = _read_file(
                    repo,
                    str(args.get("file", "")),
                    offset=int(args.get("offset", 1)),
                    limit=int(args.get("limit", MAX_READ_LINES)),
                )
            elif name == "apply_edit":
                if on_status:
                    on_status(f"Editing {args.get('file', '')}...")
                result = _apply_edit(
                    repo,
                    str(args.get("file", "")),
                    str(args.get("old_content", "")),
                    str(args.get("new_content", "")),
                    tracker,
                )
            elif name == "create_file":
                if on_status:
                    on_status(f"Creating {args.get('file', '')}...")
                result = _create_file(
                    repo,
                    str(args.get("file", "")),
                    str(args.get("content", "")),
                    tracker,
                )
            elif name == "done":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Done acknowledged.",
                    }
                )
                return args.get("summary")
            elif name == "search_tools":
                if mcp_mgr:
                    result = handle_search_tools_call(mcp_mgr, args, all_tools)
                else:
                    result = "search_tools is not available without MCP servers."
            elif mcp_mgr and mcp_mgr.has_tool(name):
                result = await mcp_mgr.call_tool(name, args)
            else:
                result = "Unknown tool."

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

        if choice.finish_reason == "stop":
            break

    return None


async def execute(
    repo: Path,
    config: Config,
    item: WorkItem,
    *,
    agent_config: AgentConfigResult | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> tuple[ExecutionResult, _ChangeTracker]:
    task_desc = _describe_item(item)
    tracker = _ChangeTracker()

    task_knowledge_desc = f"Implement code change: {task_desc[:200]}"
    if on_status:
        on_status("Selecting relevant knowledge...")
    codegen_model = config.model_for("codegen")
    knowledge_files = await select_knowledge(
        repo, config.model_for("selector"), task_knowledge_desc
    )
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    repo_conventions = "(none detected)"
    if agent_config and agent_config.has_config:
        repo_conventions = agent_config.format_for_prompt()

    extra_builtins, initial_mcp_tools, mcp_prompt = prepare_mcp_for_agent(mcp_mgr, codegen_model)
    context_prompt = EXECUTOR_CONTEXT_PROMPT.format(
        knowledge_context=knowledge_context or "(no knowledge files yet)",
        repo_conventions=repo_conventions,
        mcp_tools_section=mcp_prompt,
    )
    task_prompt = EXECUTOR_TASK_PROMPT.format(task_description=task_desc)

    messages: list[dict] = [_build_cached_message(codegen_model, context_prompt, task_prompt)]
    all_tools: list[dict] = EXECUTOR_TOOLS + extra_builtins + initial_mcp_tools

    done_summary = await _run_llm_edits(
        repo,
        codegen_model,
        messages,
        tracker,
        all_tools,
        mcp_mgr=mcp_mgr,
        on_status=on_status,
    )

    for hook in config.pre_hooks:
        if on_status:
            on_status(f"Running pre-hook: {hook}...")
        ok, output = await _run_command(repo, hook)
        if not ok:
            await _rollback(repo, tracker)
            return (
                ExecutionResult(
                    success=False,
                    diff="",
                    hooks_passed=False,
                    failed_hook=hook,
                    retries=0,
                    failure_reason=f"Pre-hook failed: {hook}",
                ),
                tracker,
            )

    max_retries = config.max_retries
    hooks_passed = True
    failed_hook: str | None = None
    retries = 0

    for attempt in range(max_retries + 1):
        hooks_passed = True
        failed_hook = None
        errors: list[str] = []

        for hook in config.post_hooks:
            if on_status:
                on_status(f"Running post-hook: {hook}...")
            ok, output = await _run_command(repo, hook)
            if not ok:
                hooks_passed = False
                failed_hook = hook
                errors.append(f"Hook `{hook}` failed:\n```\n{output[:OUTPUT_TRUNCATE_CHARS]}\n```")
                break

        if not errors:
            break

        if attempt < max_retries:
            retries += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The changes you made have errors. Fix them.\n\n"
                        + "\n\n".join(errors)
                        + "\n\nUse apply_edit to fix the issues. When done, call the done tool."
                    ),
                }
            )
            await _run_llm_edits(
                repo,
                codegen_model,
                messages,
                tracker,
                all_tools,
                mcp_mgr=mcp_mgr,
                on_status=on_status,
            )

    diff = await _get_diff(repo)
    success = hooks_passed and bool(diff)

    failure_reason = None
    if not diff:
        failure_reason = "No changes were made."
    elif not hooks_passed:
        last_error = errors[-1] if errors else ""
        failure_reason = f"Post-hooks failed after all retries.\n{last_error}"

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


def _slugify(item: WorkItem) -> str:
    if isinstance(item, Finding):
        raw = f"{item.category}-{Path(item.file).stem}"
    else:
        raw = item.title
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:50]


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
    agent_config: AgentConfigResult | None = None,
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
                downgraded=True,
                downgrade_context=f"Worktree creation failed: {e}",
            ),
            "",
        )
    result, tracker = await execute(
        worktree_path, config, item, agent_config=agent_config, mcp_mgr=mcp_mgr, on_status=on_status
    )

    if not result.success:
        desc = _describe_item(item)
        if result.diff:
            await _commit_changes(worktree_path, item, tracker)
        return (
            item,
            ExecutionResult(
                success=False,
                diff=result.diff,
                hooks_passed=result.hooks_passed,
                failed_hook=result.failed_hook,
                retries=result.retries,
                failure_reason=result.failure_reason,
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
        base = _slugify(item)
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
    agent_config: AgentConfigResult | None = None,
    mcp_mgr: MCPManager | None = None,
    on_status: StatusCallback | None = None,
) -> list[tuple[WorkItem, ExecutionResult, str]]:
    if not items:
        return []

    slugs = _dedup_slugs(items)
    sem = asyncio.Semaphore(config.max_parallel_agents)

    def _item_callback(slug: str) -> StatusCallback | None:
        if on_status is None:
            return None
        return lambda msg, _slug=slug: on_status(f"[{_slug}] {msg}")

    async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
        async with sem:
            return await _execute_in_worktree(
                repo,
                config,
                item,
                slug,
                agent_config=agent_config,
                mcp_mgr=mcp_mgr,
                on_status=_item_callback(slug),
            )

    results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))

    for slug, (_, result, branch) in zip(slugs, results):
        if not branch:
            continue
        worktree_path = repo / WORKTREE_DIR / slug
        if not result.success:
            await _cleanup_worktree(repo, worktree_path, branch)

    return results
