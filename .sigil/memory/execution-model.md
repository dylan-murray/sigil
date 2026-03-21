# Execution Model — Sigil

## Overview

Sigil uses git worktrees to execute multiple improvements simultaneously without conflicts. Each work item gets an isolated branch and worktree, runs through a generate→lint→test pipeline, and either becomes a PR or gets downgraded to an issue.

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
   → LLM generates changes via tool calls
   → lint → test → retry loop

3. _commit_changes(worktree_path, item)
   → git add -A
   → git commit -m "sigil: fix {category} in {file}"  (or "sigil: implement {title}")

4. _rebase_onto_main(repo, worktree_path)
   → git rebase main
   → if memory conflicts: auto-resolve (take main's version)
   → if code conflicts: abort, return (False, error_msg)

5. push_branch(repo, branch)
   → git push -u origin {branch}

6. open_pr(client, item, result, branch, repo)
   → GitHub API: create PR

7. cleanup_after_push(repo, results, pushed_branches)
   → git worktree remove --force {worktree_path}
   → git branch -D {branch}
```

## Code Generation Loop

The executor uses a tool-use loop with up to `MAX_TOOL_CALLS_PER_PASS = 15` iterations:

```
LLM receives: task description + knowledge context
LLM calls tools:
  read_file(file) → file content
  apply_edit(file, old_content, new_content) → "Applied edit to {file}."
  create_file(file, content) → "Created {file}."
  done(summary) → "Done acknowledged." → exits loop
```

### `apply_edit` Constraints
- `old_content` must match **exactly** (whitespace, indentation)
- If `old_content` matches 0 locations: error returned to LLM
- If `old_content` matches >1 locations: error returned to LLM (must be unique)
- Path must be within repo root (traversal blocked)

### Retry Loop
After initial code generation, lint and test are run:

```python
for attempt in range(max_retries + 1):
    errors = []
    
    if config.lint_cmd:
        ok, output = await _run_command(repo, config.lint_cmd)
        if not ok:
            errors.append(f"Lint errors:\n```\n{output[:4000]}\n```")
    
    if config.test_cmd:
        ok, output = await _run_command(repo, config.test_cmd)
        if not ok:
            errors.append(f"Test errors:\n```\n{output[:4000]}\n```")
    
    if not errors:
        break  # Success
    
    if attempt < max_retries:
        # Feed errors back to LLM for fixing
        messages.append({"role": "user", "content": "Fix these errors:\n" + errors})
        await _run_llm_edits(repo, config, messages, tracker)
```

### Rollback on Failure
If execution fails (lint/test still failing after retries, or no diff produced):
```python
await _rollback(repo, tracker)
# → git checkout -- {modified_files}
# → unlink {created_files}
```

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

Downgrade triggers:
1. **Worktree creation failed** — git error
2. **Execution failed** — lint/tests still failing after all retries
3. **No diff produced** — LLM made no changes
4. **Commit failed** — git commit error
5. **Rebase conflict** — non-memory conflict with main branch

## Parallel Execution

```python
sem = asyncio.Semaphore(config.max_parallel_agents)  # Default: 3

async def _run(item, slug):
    async with sem:
        return await _execute_in_worktree(repo, config, item, slug)

results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))
```

Slug deduplication prevents worktree path collisions:
```python
# items with same slug get -1, -2 suffixes
["dead-code-utils", "dead-code-utils-1", "dead-code-utils-2"]
```

## Memory Conflict Resolution During Rebase

When rebasing execution branch onto main:

```python
rc, stdout, _ = await arun(["git", "diff", "--name-only", "--diff-filter=U"], cwd=worktree_path)
conflicted = stdout.strip().splitlines()

memory_prefix = ".sigil/memory/"
if conflicted and all(f.startswith(memory_prefix) for f in conflicted):
    # All conflicts are in memory files — auto-resolve by taking main's version
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

## ExecutionResult Interpretation

| success | downgraded | Meaning |
|---------|------------|---------|
| True | False | PR candidate — push branch, open PR |
| False | True | Issue candidate — open issue with downgrade_context |
| False | False | (shouldn't happen — failure always sets downgraded=True) |

## Cleanup Strategy

After `publish_results()`:
- **Pushed branches:** Worktree removed, local branch deleted
- **Failed branches:** Cleaned up immediately in `execute_parallel()` (not pushed)
- **Unpushed successful branches:** Cleaned up in `cleanup_after_push()` if not in `pushed_branches`

## Command Timeouts

- `COMMAND_TIMEOUT = 120` seconds for lint/test commands
- `OUTPUT_TRUNCATE_CHARS = 4000` — error output truncated before sending to LLM
- Git operations: 10-60 seconds depending on operation
