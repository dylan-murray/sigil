# Execution Model — Worktree Isolation, Inline PR Publishing, Parallel Execution, and Cleanup

## Overview

Sigil uses git worktrees to execute multiple improvements simultaneously without conflicts. Each work item gets an isolated branch and worktree, runs through a generate→pre-hooks→post-hooks pipeline, and either becomes a PR (published inline) or gets downgraded to an issue.

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
   → LLM generates changes via Agent framework
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

7. _cleanup_worktree(repo, worktree_path, branch)
   → git worktree remove --force {worktree_path}
   → git branch -D {branch}
```

## Code Generation Loop (Agent Framework)

The executor uses the `Agent` framework. Tools are defined as `Tool` objects and the loop is handled by `Agent.run()`:

```python
from sigil.agent import Agent, Tool, ToolResult

# Tools defined as Tool objects
read_tool = Tool(name="read_file", ...)
apply_edit_tool = Tool(name="apply_edit", ...)
create_file_tool = Tool(name="create_file", ...)
done_tool = Tool(name="done", ...)

# Agent configured with tools
executor = Agent(label="execution", model=config.model, tools=[...], ...)
result = await executor.run(context={...}, on_status=on_status)
```

### `read_file` Truncation
- **Line cap:** 2000 lines maximum
- **Byte cap:** 50KB maximum
- **Offset/limit:** Supports `offset` (1-based) and `limit` params
- **Truncation message:** `"[truncated — {total} lines total. Use read_file with offset={next_line} to continue.]"`

### `apply_edit` Constraints
- `old_content` must match **exactly** (whitespace, indentation, no partial matches)
- If `old_content` matches 0 or >1 locations: error returned to LLM
- Path must be within repo root (traversal blocked by `_validate_path`)
- **Write protection:** `.sigil/` directory is write-protected

### `_ChangeTracker`
Tracks which files were modified/created during execution for rollback and commit.

### Pre-Hooks
Before code generation, pre-hooks are run. If any pre-hook fails, execution is aborted immediately and the item is downgraded to an issue.

### Post-Hooks Retry Loop
After code generation, post-hooks are run with retry. If any post-hook fails, the LLM is given the error output and retries (up to `max_retries`). If all retries fail, item is downgraded to an issue.

### Rollback on Failure
If execution fails: `git checkout -- {modified_files}` and `unlink {created_files}`

### Truncation Circuit Breaker
After 3 consecutive truncations, the loop breaks to prevent infinite retry attempts.

### Summary Generation from Diff
If the LLM's summary is missing or too short (< 200 chars), Sigil generates a summary from the git diff using a cheap model.

## Cost Optimization in Executor

### Observation Masking
Before each `acompletion()` call, `mask_old_tool_outputs(messages)` replaces tool result content older than the last 10 messages with placeholders.

### Client-Side Compaction
When estimated input tokens exceed 80k, `compact_messages()` uses a cheap model (Haiku) to summarize old context.

### Prompt Caching
For models supporting prompt caching, executor builds cached messages with `cache_control: {"type": "ephemeral"}`.

### Doom Loop Detection
Before each `acompletion()` call, `detect_doom_loop(messages)` checks if last 3 tool calls are identical.

### Per-Agent Output Caps
Executor uses `get_agent_output_cap("codegen", model)` → 32k tokens.

## Failure Downgrade

When execution fails, the item is downgraded to a GitHub issue:

```python
ExecutionResult(
    success=False,
    downgraded=True,
    downgrade_context="Execution failed after N retries.\nReason: ...",
)
```

Downgrade triggers: worktree creation failed, execution failed (hooks), no diff produced, commit failed, rebase conflict.

## Parallel Execution

```python
async def execute_parallel(
    repo, config, items, slugs, *,
    gh_client: GitHubClient | None = None,
    models_section: str = "",
    on_pr_published: Callable[[WorkItem, str], None] | None = None,
    on_issue_downgrade: Callable[[WorkItem, str | None], None] | None = None,
    ...
) -> list[tuple[WorkItem, ExecutionResult, str]]:
```

When `gh_client` is provided, PRs are published **inline** as each item finishes, via `_publish_and_cleanup()`. This means:
- Successful items with diff → PR opened immediately, worktree cleaned up
- Downgraded items without diff → `on_issue_downgrade` callback fires, worktree cleaned up
- Downgraded items with diff → PR opened, worktree cleaned up

When `gh_client` is `None` (dry run), cleanup still happens for failed items without diff.

Slug deduplication prevents worktree path collisions (items with same slug get `-1`, `-2` suffixes).

## Inline PR Publishing

When `gh_client` is provided to `execute_parallel`, each item is published as it completes:

```python
async def _publish_and_cleanup(item, result, branch, slug):
    if not branch:
        return
    worktree_path = repo / WORKTREE_DIR / slug
    try:
        if result.diff and (result.success or result.downgraded):
            url = await open_pr(gh_client, item, result, branch, repo, ...)
            if url and on_pr_published:
                on_pr_published(item, url)
        elif result.downgraded and not result.diff and on_issue_downgrade:
            on_issue_downgrade(item, result.downgrade_context)
    finally:
        await _cleanup_worktree(repo, worktree_path, branch)
```

This replaces the old post-hoc `publish_results()` + `cleanup_after_push()` pattern.

## Memory Conflict Resolution During Rebase

When rebasing execution branch onto main:
- Memory file conflicts → auto-resolve by taking main's version
- Code conflicts → abort rebase and downgrade to issue

## ExecutionResult Interpretation

| success | downgraded | Meaning |
|---------|------------|----------|
| True | False | PR candidate — push branch, open PR |
| False | True | Issue candidate — open issue with downgrade_context |
| False | False | (shouldn't happen — failure always sets downgraded=True) |

## Cleanup Strategy

Cleanup now happens **inline** during execution:
- **With gh_client:** `_publish_and_cleanup()` handles PR opening and worktree cleanup together
- **Without gh_client:** Cleanup happens in a post-loop pass for failed items without diff
- **No separate cleanup step:** The old `cleanup_after_push()` function has been removed

## Command Timeouts

- `COMMAND_TIMEOUT = 120` seconds for pre/post hook commands
- `OUTPUT_TRUNCATE_CHARS = 4000` — error output truncated before sending to LLM
- Git operations: 10–60 seconds depending on operation

## Known Issue

`execute_parallel` returns `branch=""` (empty string) as sentinel for "worktree creation failed". This should be `str | None` for type safety.
