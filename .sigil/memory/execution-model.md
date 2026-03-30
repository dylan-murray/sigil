<!-- head: 05afd4a | updated: 2026-03-25T03:37:29Z -->

# Execution Model — How Sigil Implements Code Changes

## Overview
Sigil uses git worktrees to execute multiple improvements simultaneously without conflicts. Each work item gets an isolated branch and worktree, runs through a generate→pre-hooks→post-hooks pipeline, and either becomes a PR or gets downgraded to an issue.

## Worktree Architecture

### Branch Strategy
- **Main branch:** Never modified directly during execution
- **Execution branches:** `sigil/auto/<slug>-<unix_timestamp>`
- **Isolation:** Each item gets its own worktree at `.sigil/worktrees/<slug>/`
- **Memory snapshot:** `.sigil/memory/` copied to worktree at creation time

### Worktree Lifecycle
```
1. _create_worktree(repo, slug)
   → git worktree add .sigil/worktrees/<slug> -b sigil/auto/<slug>-<ts>
   → copy .sigil/memory/ to worktree (snapshot)

2. execute(worktree_path, config, item)
   → LLM generates changes via Agent framework (ticket 073)
   → pre-hooks → post-hooks → retry loop

3. _commit_changes(worktree_path, item, tracker)
   → git add -- {modified_files} {created_files}
   → git commit -m "sigil: fix {category} in {file}"  (or "sigil: implement {title}")

4. _rebase_onto_main(repo, worktree_path)
   → git rebase main
   → if memory conflicts: auto-resolve (take main's version via --ours)
   → if code conflicts: abort, return (False, error_msg)

5. push_branch(repo, branch)
   → git push -u origin {branch}

6. open_pr(client, item, result, branch, repo)
   → GitHub API: create PR with LLM-generated summary

7. cleanup_after_push(repo, results, pushed_branches)
   → git worktree remove --force {worktree_path}
   → git branch -D {branch}
```

## Code Generation Loop (Agent Framework)
The executor uses the `Agent` framework (ticket 073). Tools are defined as `Tool` objects and the loop is handled by `Agent.run()`:

```python
from sigil.core.agent import Agent, Tool, ToolResult

# Tools defined as Tool objects
read_tool = Tool(
    name="read_file",
    description="Read file content (capped at 2000 lines / 50KB).",
    parameters={...},
    handler=_read_file_handler,
)

apply_edit_tool = Tool(
    name="apply_edit",
    description="Apply an edit to a file.",
    parameters={...},
    handler=_apply_edit_handler,
)

create_file_tool = Tool(
    name="create_file",
    description="Create a new file.",
    parameters={...},
    handler=_create_file_handler,
)

done_tool = Tool(
    name="task_progress", # Renamed from 'done' to 'task_progress'
    description="Signal completion with a summary.",
    parameters={...},
    handler=_done_handler,  # returns ToolResult(stop=True, result=summary)
)

# Agent configured with tools
executor = Agent(
    label="engineer", # Renamed from 'execution' to 'engineer'
    model=config.model,
    tools=[read_tool, apply_edit_tool, create_file_tool, done_tool],
    system_prompt=executor_prompt,
    max_rounds=config.max_iterations_for("engineer"), # Uses config.max_iterations_for
    max_tokens=config.max_tokens_for("engineer"), # Uses config.max_tokens_for
    on_truncation=_executor_truncation_handler,  # handles consecutive truncations
)

# Run the agent
result = await executor.run(
    messages=[{"role": "user", "content": context_prompt}], # Uses messages directly
    on_status=on_status,
)

# result: AgentResult with messages, rounds, stop_result (summary from task_progress tool)
```

### `read_file` Truncation
- **Line cap:** 2000 lines maximum
- **Byte cap:** 50KB maximum
- **Offset/limit:** Supports `offset` (1-based line number) and `limit` (max lines to return). Must be a single integer, NOT a list or range. To read lines 300-420, use offset=300 and limit=120.
- **Truncation message:** If output is truncated, appends `"[truncated — {total} lines total. Use read_file with offset={next_line} to continue.]"`

### `apply_edit` Constraints
- `old_content` must match **exactly** (whitespace, indentation, no partial matches)
- If `old_content` matches 0 locations: error returned to LLM
- If `old_content` matches >1 locations: error returned to LLM (must be unique)
- Path must be within repo root (traversal blocked by `_validate_path`)
- **Write protection:** `.sigil/` directory is write-protected; cannot modify memory/config files
- **Known gap:** No guard against empty `old_content` (could replace entire file)

### `FileTracker`
Tracks which files were modified/created during execution for rollback and commit:
```python
@dataclass
class FileTracker:
    modified: set[str]   # Files touched by apply_edit
    created: set[str]    # Files created by create_file
    last_read: dict[str, float] # Timestamp of last read for staleness check
```

### Pre-Hooks
Before code generation, pre-hooks are run:

```python
for hook in config.pre_hooks:
    ok, output = await _run_command(repo, hook)
    if not ok:
        await _rollback(repo, tracker)
        return ExecutionResult(
            success=False,
            diff="",
            hooks_passed=False,
            failed_hook=hook,
            failure_reason=f"Pre-hook failed: {hook}",
            failure_type=FailureType.PRE_HOOK,
        )
```

- **Pre-hooks** run before LLM code generation
- If any pre-hook fails, execution is aborted immediately
- Item is downgraded to an issue
- Remaining pre-hooks are not executed

### Post-Hooks Retry Loop
After initial code generation, post-hooks are run with retry:

```python
for round_num in range(max_rounds):
    hooks_ok = True
    failed_hook_name: str | None = None
    hook_results: list[tuple[str, str]] = []

    # ... run post-hooks ...

    if hooks_ok:
        break  # Success

    if round_num < max_rounds - 1:
        # Feed errors back to LLM for fixing
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
```

- **Post-hooks** run after code generation
- If any post-hook fails, the LLM is given the error output and retries (up to `max_retries` from config)
- Hooks run in order; any failure short-circuits the list
- If all retries fail, item is downgraded to an issue

### Rollback on Failure
If execution fails (hooks still failing after retries, or no diff produced):
```python
await _rollback(repo, tracker)
# → git checkout -- {modified_files}
# → unlink {created_files}
```

### Truncation Circuit Breaker
The executor uses `on_truncation` callback to handle consecutive output truncations:

```python
def _executor_truncation_handler(messages: list[dict], choice: object, count: int) -> bool:
    max_consecutive = 3
    if count >= max_consecutive:
        logger.warning("Model output cap too small — %d consecutive truncations, aborting", count)
        return False  # Stop the loop
    # Otherwise, append continuation prompt and continue
    messages.append(...)
    return True
```

After 3 consecutive truncations, the loop breaks to prevent infinite retry attempts.

### Summary Generation from Diff
After execution completes, if the LLM's summary is missing or too short (< 200 chars), Sigil generates a summary from the git diff:

```python
async def _generate_summary_from_diff(
    diff: str, task_description: str, existing_summary: str | None, model: str
) -> str:
    # LLM summarizes diff into bulleted list
    # Falls back to existing_summary if generation fails
```

This ensures PR descriptions are always informative even if the executor's done summary was inadequate.

## Cost Optimization in Executor

### Observation Masking
Before each `acompletion()` call, `mask_old_tool_outputs(messages)` replaces tool result content older than the last 6 messages with placeholders:
- `read_file` results → `"[file contents omitted — use read_file again if needed]"`
- `apply_edit`/`create_file` results → kept as-is (small, important)
- Error traces → kept as-is (losing them causes repeated mistakes)
- MCP results → `"[tool result omitted — call again if needed]"`

### Client-Side Compaction
When estimated input tokens exceed `get_compaction_threshold(model)` (typically 40% of context window), `compact_messages(messages, model)` uses the active model to summarize old context:
- Collects messages older than last 5 turns
- Sends to model with compaction prompt
- Replaces old messages with single summary user message
- Never breaks tool-call/result message pairs

### Prompt Caching
For models supporting prompt caching, executor builds cached messages:
- Context (knowledge, conventions) marked with `cache_control: {"type": "ephemeral"}`
- Task description in separate text block
- Reduces cost on subsequent calls to same item

### Doom Loop Detection
Before each `acompletion()` call, `detect_doom_loop(messages)` checks if last 5 tool calls are identical (same name + arguments). If so, breaks the loop with warning.

### Per-Agent Output Caps
Executor uses `config.max_tokens_for("engineer")` to cap output. Prevents runaway output.

## Failure Downgrade
When execution fails, the item is downgraded to a GitHub issue instead of a PR:

```python
ExecutionResult(
    success=False,
    downgraded=True,
    downgrade_context=(
        f"Execution failed after {result.retries} retries.\n"
        f"Reason: {result.failure_reason}\n"
        f"Task: {desc[:500]}"
    ),
    ...
)
```

Downgrade triggers (5 cases):
1. **Worktree creation failed** — git error (OSError from `_create_worktree`)
2. **Execution failed** — hooks still failing after all retries
3. **No diff produced** — LLM made no changes (`failure_reason = "No changes were made."`) or pre-hook failed
4. **Commit failed** — git commit error
5. **Rebase conflict** — non-memory conflict with main branch

## Parallel Execution

```python
sem = asyncio.Semaphore(config.max_parallel_tasks)  # Default: 3

async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
    async with sem:
        return await _execute_in_worktree(repo, config, item, slug)

results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))
```

Slug deduplication prevents worktree path collisions:
```python
# items with same slug get -1, -2 suffixes
["dead-code-utils", "dead-code-utils-1", "dead-code-utils-2"]
```

Failed worktrees are cleaned up immediately in `execute_parallel()` (before `publish_results`).

## Memory Conflict Resolution During Rebase
When rebasing execution branch onto main:

```python
rc, stdout, _ = await arun(["git", "diff", "--name-only", "--diff-filter=U"], cwd=worktree_path)
conflicted = [f for f in stdout.strip().splitlines() if f]

memory_prefix = ".sigil/memory/"
if conflicted and all(f.startswith(memory_prefix) for f in conflicted):
    # All conflicts are in memory files — auto-resolve by taking main's version via --ours
    for f in conflicted:
        await arun(["git", "checkout", "--ours", f], cwd=worktree_path)
        await arun(["git", "add", f], cwd=worktree_path)
    await arun(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=worktree_path)
    # → Success
else:
    # Code conflicts — abort and downgrade
    await arun(["git", "rebase", "--abort"], cwd=worktree_path)
    # → Downgrade to issue
```

**Rationale:** Main branch has authoritative memory state. Execution branch memory is discarded on conflict.

**Note on stash:** `_rebase_onto_main` stashes dirty working tree files before rebasing and pops the stash after, to handle cases where memory files are dirty (not committed) in the worktree.

## ExecutionResult Interpretation

| success | downgraded | Meaning |
|---------|------------|----------|
| True | False | PR candidate — push branch, open PR |
| False | True | Issue candidate — open issue with downgrade_context |
| False | False | (shouldn't happen — failure always sets downgraded=True) |

## Cleanup Strategy
After `publish_results()`:
- **Pushed branches:** `cleanup_after_push()` removes worktree + local branch
- **Failed branches:** Cleaned up immediately in `execute_parallel()` (not pushed)
- **Unpushed successful branches:** Cleaned up in `cleanup_after_push()` only if they have a diff (no diff = no branch to push)

## Cleanup Logic Detail

In `execute_parallel()`, cleanup happens for failed executions:
```python
if not result.success and not result.diff:
    await _cleanup_worktree(repo, worktree_path, branch)
```

This ensures:
- Worktrees with no diff are cleaned up immediately (no PR will be created)
- Worktrees with diff but failed hooks are NOT cleaned up (may be retried or downgraded to issue)
- Only branches that were successfully pushed are cleaned up in `cleanup_after_push()`

## Command Timeouts

- `COMMAND_TIMEOUT = 120` seconds for pre/post hook commands
- `OUTPUT_TRUNCATE_CHARS = 12000` — error output truncated before sending to LLM
- Git operations: 10–60 seconds depending on operation (worktree add: 30s, rebase: 60s)

## Known Issue
`execute_parallel` returns `branch=""` (empty string) as sentinel for "worktree creation failed". This should be `str | None` for type safety. The caller checks `if not branch` or `if branch` to distinguish.
