# Pipeline Architecture — 8-Stage Async Agentic Workflow

Sigil runs an 8-stage async pipeline. Each stage is optional and can be skipped via config or CLI flags.

## Pipeline Stages

### 1. Discovery (maintenance)
Scans the repository for issues using `list_directory`, `grep`, and `read_file` tools. Produces `Finding` objects with category, file, description, and triage recommendation. Uses the `discovery` agent.

### 2. Ideation (ideation)
Generates new feature ideas using **multi-instance parallel ideators**. Each configured ideator instance (potentially different models) runs independently with the same system prompt but its own quota of ideas. Results are merged, deduplicated, and sorted by priority.

Previously used a two-temperature approach (low-temp focused + high-temp creative passes on the same model). Now uses diverse models in parallel for broader perspective.

Each idea records its `generated_by` field (the model that produced it) for attribution in PR bodies.

### 3. Validation (validation)
Single-pass triager evaluates all findings and ideas. The parallel challenger+arbiter mode has been removed — validation is now always a single triager pass. The triager uses `review_item` tool to approve, adjust, or veto each candidate, optionally changing its disposition (pr/issue/skip).

### 4. Architect (executor)
For each approved item, the architect reads relevant files and produces an implementation plan. The plan includes:
- **Goal** — WHAT is being built (user-visible behavior, scope, acceptance criteria). The engineer sees ONLY this plan, not the original task description.
- **Approach** — key design decisions
- **Files to Modify** — per-file behavioral changes
- **Integration Points** — ALL downstream call sites affected by each change (found via grep during analysis)
- **Files to Create** — new files and their public interfaces

The architect prompt warns against prescribing HOW (file paths, function names, code structure) since the ideator that wrote suggestions did NOT read the code.

### 5. Engineer (executor)
Implements the architect's plan in an isolated worktree. Uses `apply_edit`, `multi_edit`, `create_file`, `read_file`, `grep`, `list_directory`, and `bash` tools. After implementation, runs post-commit hooks and fixes failures.

The engineer prompt mandates re-reading a file before every `apply_edit`/`multi_edit` — memory of file content is stale after edits.

### 6. Reviewer (executor)
Reviews the diff produced by the engineer. Can request changes, which loops back to the engineer.

### 7. Auditor (executor)
Scans the final diff for bugs, security issues, and regressions.

### 8. Publish (github)
PRs are published **inline** during parallel execution — as each item finishes, `execute_parallel` opens the PR immediately via `_publish_and_cleanup()`. This means PRs appear on GitHub as soon as they're ready, rather than waiting for all items to complete.

Issues are published in a separate step after execution completes, via `publish_issues()`. Downgraded items (execution failures) are collected during execution via the `on_issue_downgrade` callback and combined with issue-disposition items.

PR bodies include model attribution (which models generated each idea).

## Execution Isolation

Each item executes in its own git worktree. Worktrees are created from a shared base branch and rebased onto main before publishing. See `execution-model.md` for details.

## Agent Loop

The `reduce_context` function is no longer called unconditionally after every agent round. It is only invoked when:
- Context pressure exceeds a threshold (token count nearing limit)
- A `ContextOverflowError` is caught during generation

This prevents unnecessary masking of tool results mid-conversation, which caused engineers to re-read the same files repeatedly.
