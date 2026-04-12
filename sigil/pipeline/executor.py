import asyncio
import logging
import shutil
import time
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
from sigil.core.tools import (
    _read_file as _read_file,  # noqa: F401 — re-exported for tests
    apply_edit,
    create_file,
    list_directory,
    make_executor_tools,
    make_grep_tool,
    make_list_dir_tool,
    make_read_file_tool,
    make_verify_hook_tool,
)
from sigil.core.utils import StatusCallback, arun, now_utc, read_file
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.knowledge import select_memory
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.models import (
    FileTracker,
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
    EXECUTOR_TASK_PROMPT_WITH_TEST,
    HOOK_FIX_INJECT_PROMPT,
    HOOK_SUMMARIZE_PROMPT,
)
from sigil.pipeline.test_writer import run_test_writer
from sigil.state.attempts import AttemptRecord, format_attempt_history, log_attempt, read_attempts
from sigil.state.chronic import WorkItem, fingerprint as item_fingerprint, slugify
from sigil.state.memory import compute_manifest_hash, load_working, update_working

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT = 120
OUTPUT_TRUNCATE_CHARS = 12000
MIN_SUMMARY_LENGTH = 200
MAX_PRELOAD_FILES = 15
MAX_PRELOAD_BYTES = 100_000
DIFF_PER_FILE_CAP = 4000
DIFF_TOTAL_CAP = 15000
MAX_REVIEWER_TOOL_CALLS = 20
WORKTREE_DIR = ".sigil/worktrees"

_ChangeTracker = FileTracker
_make_executor_tools = make_executor_tools


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
    tracker: "FileTracker | None" = None,
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


def _apply_edit(
    repo: Path,
    file: str,
    old_content: str,
    new_content: str,
    tracker: FileTracker,
    ignore: list[str] | None = None,
) -> str:
    return apply_edit(repo, file, old_content, new_content, tracker=tracker, ignore=ignore)


def _create_file(
    repo: Path,
    file: str,
    content: str,
    tracker: FileTracker,
    ignore: list[str] | None = None,
) -> str:
    return create_file(repo, file, content, tracker=tracker, ignore=ignore)


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
    prompt = (
        "Summarize the following code change in 2-4 sentences. "
        "Name the files and functions that changed. "
        "Focus on what changed and why, not how.\n\n"
        f"Task: {task_description}\n\n"
        f"Agent's notes: {existing_summary or '(none)'}\n\n"
        f"Diff:\n```\n{diff[:12_000]}\n```"
    )
    try:
        response = await acompletion(
            label="engineer:summary",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=500,
        )
        content = response.choices[0].message.content
        if content and len(content.strip()) >= MIN_SUMMARY_LENGTH:
            return content.strip()
    except (KeyError, IndexError, AttributeError) as e:
        logger.warning("Summary generation failed: %s", e)
    return existing_summary or ""


async def _run_command(repo: Path, cmd: str) -> tuple[bool, str]:
    rc, stdout, stderr = await arun(cmd, cwd=repo, timeout=COMMAND_TIMEOUT)
    output = (stdout + "\n" + stderr).strip()
    return rc == 0, output


async def _rollback(repo: Path, tracker: FileTracker) -> None:
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
    logger.debug(
        "Executor output truncated (finish_reason=length) — %d/%d consecutive",
        count,
        max_consecutive,
    )
    if count >= max_consecutive:
        logger.warning(
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
        logger.debug("Hook summarization failed, using raw output: %s", exc)
    return raw_output


def _prepare_diff_for_review(diff: str, tracker: FileTracker) -> str:
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

    architect_tracker = FileTracker()
    tools = [
        make_read_file_tool(repo, on_status, ignore, tracker=architect_tracker),
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
        max_rounds=config.max_iterations_for("architect"),
        max_tokens=config.max_tokens_for("architect") or 16_384,
        forced_final_tool="submit_plan",
        reasoning_effort=config.reasoning_effort_for("architect"),
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
        logger.warning("Architect did not call submit_plan — using last text response as plan")
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
    failing_test_context: str | None = None,
) -> tuple[ExecutionResult, FileTracker]:
    task_desc = _describe_item(item)
    tracker = FileTracker()

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
        logger.warning("Knowledge selection failed: %s — proceeding without knowledge", exc)
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

    preloaded = _preload_relevant_files(repo, item, ignore=config.effective_ignore, tracker=tracker)

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

    # Run test-writer (Red phase) before implementation if configured
    failing_test_context: str | None = None
    test_writer_configured = config.model_for("test_writer") != config.model
    if item.disposition == "pr" and test_writer_configured:
        if on_status:
            on_status("Writing failing test (Red phase)...")
        try:
            failing_test_context = await run_test_writer(
                repo,
                config,
                item,
                task_desc,
                memory_context,
                working_md or "",
                repo_conventions,
                preloaded_files=preloaded,
                ignore=config.effective_ignore,
                on_status=on_status,
            )
            if failing_test_context:
                if on_status:
                    on_status("Failing test written — engineer will make it pass")
            else:
                logger.warning("Test-Writer produced no test — proceeding without it")
                if on_status:
                    on_status("Test-Writer produced nothing — proceeding normally")
        except Exception as exc:
            logger.warning("Test-Writer failed: %s — proceeding without it", exc)
            if on_status:
                on_status("Test-Writer error — proceeding without failing test")

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
            ignore=config.effective_ignore,
            on_status=on_status,
        )

    if failing_test_context:
        task_prompt = EXECUTOR_TASK_PROMPT_WITH_TEST.format(
            task_description=task_desc + task_suffix,
            plan=architect_plan or "(no plan provided)",
            failing_test=failing_test_context,
        )
    elif architect_plan:
        if on_status:
            preview = architect_plan[:200].replace("\n", " ")
            on_status(f"Architect plan: {preview}...")
        logger.info("Architect plan for %s:\n%s", task_desc[:80], architect_plan)
        task_prompt = EXECUTOR_TASK_PROMPT_WITH_PLAN.format(
            task_description=task_desc + task_suffix,
            plan=architect_plan,
        )
    else:
        if architect_configured and on_status:
            on_status("Architect produced no plan — engineer will explore independently")
        task_prompt = EXECUTOR_TASK_PROMPT.format(task_description=task_desc) + task_suffix

    messages: list[dict] = [_build_cached_message(engineer_model, context_prompt, task_prompt)]

    ignore = config.effective_ignore or None
    executor_tools = _make_executor_tools(repo, tracker, on_status, ignore=ignore)
    extra_schemas = extra_builtins + initial_mcp_tools

    engineer_agent = Agent(
        label="engineer",
        model=engineer_model,
        tools=executor_tools,
        system_prompt=ENGINEER_SYSTEM_PROMPT.format(repo_conventions=repo_conventions),
        max_rounds=config.max_iterations_for("engineer"),
        max_tokens=config.max_tokens_for("engineer") or 32_768,
        on_truncation=_executor_truncation_handler,
        mcp_mgr=mcp_mgr,
        extra_tool_schemas=extra_schemas,
        reasoning_effort=config.reasoning_effort_for("engineer"),
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
        logger.warning("Doom loop detected in engineer agent — stopping execution")

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
            failed_cmds = [hook for hook, _ in hook_results]
            verify_tool = make_verify_hook_tool(repo, failed_cmds, on_status)
            engineer_agent.add_tool(verify_tool)
            inject = HOOK_FIX_INJECT_PROMPT.format(error_block=error_block)
            coord.inject("engineer", {"role": "user", "content": inject})
            engineer_result = await coord.run_agent("engineer", on_status=on_status)
            engineer_agent.remove_tool("verify_hook")
            if engineer_result.doom_loop:
                doom_loop = True
            continue

    diff = await _get_diff(repo)
    has_real_changes = bool(tracker.modified or tracker.created)
    success = hooks_ok and bool(diff) and has_real_changes

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
    worktree_path: Path, item: WorkItem, tracker: FileTracker
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

    rc_head, head_ref, _ = await arun(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
        cwd=worktree_path,
        timeout=10,
    )
    default_branch = head_ref.strip().removeprefix("origin/") if rc_head == 0 else "main"

    rc, _, stderr = await arun(["git", "rebase", default_branch], cwd=worktree_path, timeout=60)
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
                logger.warning("Downgrade commit failed for %s: %s", slug, commit_err)
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

    desc = _describe_item(item)
    item_context = (
        f"Executed: {desc[:300]}\n"
        f"Result: {'success' if result.success else 'failed'}, "
        f"retries: {result.retries}\n"
        f"Summary: {result.summary[:500]}"
    )

    manifest_hash = await compute_manifest_hash(worktree_path)

    if on_status:
        on_status("Updating working memory...")
    try:
        working_path = await update_working(
            worktree_path,
            config.model_for("memory"),
            item_context,
            manifest_hash=manifest_hash,
            max_tokens=config.max_tokens_for("memory"),
        )
    except Exception as exc:
        logger.warning("Working memory update failed for %s: %s", slug, exc)
        working_path = None

    if working_path:
        rc_add, _, _ = await arun(["git", "add", working_path], cwd=worktree_path, timeout=10)
        if rc_add == 0:
            rc_amend, _, stderr = await arun(
                ["git", "commit", "--amend", "--no-edit"],
                cwd=worktree_path,
                timeout=30,
            )
            if rc_amend != 0:
                logger.warning("Failed to amend commit with working memory: %s", stderr.strip())
                await arun(["git", "reset", "HEAD"], cwd=worktree_path, timeout=10)

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
    sem = asyncio.Semaphore(config.max_parallel_tasks)
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
                logger.warning("Failed to write attempt log")

            return result_tuple

    results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))

    for slug, (_, result, branch) in zip(slugs, results):
        if not branch:
            continue
        worktree_path = repo / WORKTREE_DIR / slug
        if not result.success and not result.diff:
            await _cleanup_worktree(repo, worktree_path, branch)

    return results
