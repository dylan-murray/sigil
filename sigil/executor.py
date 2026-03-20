from __future__ import annotations

import json
import re
import shutil
import subprocess
import asyncio
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Union

import litellm

from sigil.config import Config
from sigil.ideation import FeatureIdea
from sigil.knowledge import select_knowledge
from sigil.maintenance import Finding


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    diff: str
    lint_passed: bool
    tests_passed: bool
    retries: int
    failure_reason: str | None


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
            "files you need to understand before making edits."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Path to the file to read, relative to the repo root.",
                },
            },
            "required": ["file"],
        },
    },
}

EXECUTOR_TOOLS = [READ_FILE_TOOL, APPLY_EDIT_TOOL, CREATE_FILE_TOOL, DONE_TOOL]

EXECUTOR_PROMPT = """\
You are Sigil, an autonomous code improvement agent. Your job is to implement
a specific code change in a repository.

Here is the task:

{task_description}

Here is the project knowledge (architecture, patterns, conventions):

{knowledge_context}

Use the read_file tool to inspect any files you need to understand before
making changes. Then use apply_edit to make surgical edits to existing files,
or create_file to create new files. Make the minimum change needed.

When you are done making all changes, call the done tool with a brief summary.

Rules:
- Read files before editing them — understand context first
- Make the smallest change that correctly addresses the task
- Do not add comments unless the logic is non-obvious
- Preserve existing code style and conventions
- Only edit files that need to change
- Do not refactor unrelated code
"""


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


def _read_file(repo: Path, file: str) -> str:
    path = _validate_path(repo, file)
    if path is None:
        return f"Access denied: {file} is outside the repository."
    if not path.exists():
        return f"File not found: {file}"
    if not path.is_file():
        return f"Not a file: {file}"
    try:
        return path.read_text()
    except OSError as e:
        return f"Cannot read {file}: {e}"


def _get_diff(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _run_command(repo: Path, cmd: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=120,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out after 120 seconds."
    except FileNotFoundError:
        return False, f"Command not found: {cmd}"


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


def _rollback(repo: Path, tracker: _ChangeTracker) -> None:
    if tracker.modified:
        try:
            subprocess.run(
                ["git", "checkout", "--"] + list(tracker.modified),
                cwd=repo,
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    for file in tracker.created:
        path = repo / file
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _run_llm_edits(
    repo: Path,
    config: Config,
    messages: list[dict],
    tracker: _ChangeTracker,
) -> str | None:
    for _ in range(15):
        response = litellm.completion(
            model=config.model,
            messages=messages,
            tools=EXECUTOR_TOOLS,
            temperature=0.0,
            max_tokens=8192,
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
                result = _read_file(repo, str(args.get("file", "")))
            elif name == "apply_edit":
                result = _apply_edit(
                    repo,
                    str(args.get("file", "")),
                    str(args.get("old_content", "")),
                    str(args.get("new_content", "")),
                    tracker,
                )
            elif name == "create_file":
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


def execute(repo: Path, config: Config, item: WorkItem) -> ExecutionResult:
    task_desc = _describe_item(item)
    tracker = _ChangeTracker()

    task_knowledge_desc = f"Implement code change: {task_desc[:200]}"
    knowledge_files = select_knowledge(repo, config.model, task_knowledge_desc)
    knowledge_context = ""
    if knowledge_files:
        parts = []
        for name, content in knowledge_files.items():
            parts.append(f"### {name}\n{content}")
        knowledge_context = "\n\n".join(parts)

    prompt = EXECUTOR_PROMPT.format(
        task_description=task_desc,
        knowledge_context=knowledge_context or "(no knowledge files yet)",
    )

    messages: list[dict] = [{"role": "user", "content": prompt}]

    _run_llm_edits(repo, config, messages, tracker)

    max_retries = config.max_retries
    lint_passed = True
    tests_passed = True
    retries = 0

    for attempt in range(max_retries + 1):
        lint_passed = True
        tests_passed = True
        errors: list[str] = []

        if config.lint_cmd:
            ok, output = _run_command(repo, config.lint_cmd)
            lint_passed = ok
            if not ok:
                errors.append(f"Lint errors:\n```\n{output[:4000]}\n```")

        if config.test_cmd:
            ok, output = _run_command(repo, config.test_cmd)
            tests_passed = ok
            if not ok:
                errors.append(f"Test errors:\n```\n{output[:4000]}\n```")

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
            _run_llm_edits(repo, config, messages, tracker)

    diff = _get_diff(repo)
    success = lint_passed and tests_passed and bool(diff)

    failure_reason = None
    if not diff:
        failure_reason = "No changes were made."
    elif not lint_passed and not tests_passed:
        failure_reason = "Lint and tests failed after all retries."
    elif not lint_passed:
        failure_reason = "Lint failed after all retries."
    elif not tests_passed:
        failure_reason = "Tests failed after all retries."

    if not success:
        _rollback(repo, tracker)

    return ExecutionResult(
        success=success,
        diff=diff,
        lint_passed=lint_passed,
        tests_passed=tests_passed,
        retries=retries,
        failure_reason=failure_reason,
    )


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


def _create_worktree(repo: Path, slug: str) -> tuple[Path, str]:
    branch = _branch_name(slug)
    worktree_path = repo / WORKTREE_DIR / slug
    if worktree_path.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=repo,
            capture_output=True,
            timeout=30,
        )
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch],
        cwd=repo,
        capture_output=True,
        timeout=30,
        check=True,
    )
    memory_src = repo / ".sigil" / "memory"
    if memory_src.exists():
        memory_dst = worktree_path / ".sigil" / "memory"
        memory_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(memory_src, memory_dst, dirs_exist_ok=True)
    return worktree_path, branch


def _execute_in_worktree(
    repo: Path, config: Config, item: WorkItem, slug: str
) -> tuple[WorkItem, ExecutionResult, str]:
    try:
        worktree_path, branch = _create_worktree(repo, slug)
    except (subprocess.CalledProcessError, OSError) as e:
        return (
            item,
            ExecutionResult(
                success=False,
                diff="",
                lint_passed=False,
                tests_passed=False,
                retries=0,
                failure_reason=f"Worktree creation failed: {e}",
            ),
            "",
        )
    result = execute(worktree_path, config, item)
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


def _cleanup_worktree(repo: Path, worktree_path: Path, branch: str) -> None:
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=repo,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    try:
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=repo,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


async def execute_parallel_async(
    repo: Path, config: Config, items: list[WorkItem]
) -> list[tuple[WorkItem, ExecutionResult, str]]:
    if not items:
        return []

    slugs = _dedup_slugs(items)
    sem = asyncio.Semaphore(config.max_parallel_agents)

    async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
        async with sem:
            return await asyncio.to_thread(_execute_in_worktree, repo, config, item, slug)

    results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))

    for slug, (_, result, branch) in zip(slugs, results):
        if not branch:
            continue
        worktree_path = repo / WORKTREE_DIR / slug
        if not result.success:
            _cleanup_worktree(repo, worktree_path, branch)

    return results


def execute_parallel(
    repo: Path, config: Config, items: list[WorkItem]
) -> list[tuple[WorkItem, ExecutionResult, str]]:
    return asyncio.run(execute_parallel_async(repo, config, items))
