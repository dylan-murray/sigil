# Worktree-Based Parallel Execution with Pre/Post Hook Pipeline

The executor agent (`sigil/pipeline/executor.py`) uses a specific set of tools to modify the codebase safely.

## Tools
- **`read_file`:** Reads file content with pagination (2000 line / 50KB limit).
- **`apply_edit`:** Surgical find-and-replace. Requires an exact match of `old_content` to ensure the agent has read the latest version.
- **`multi_edit`:** Applies multiple sequential edits to a single file atomically.
- **`create_file`:** Creates new files (fails if the file already exists).
- **`grep`:** Searches the codebase using regex to find callers and imports.
- **`task_progress`:** A mandatory final tool where the agent must provide a 200+ character summary of changes.

## Safety Mechanisms
- **Write Protection:** The agent is blocked from modifying any files inside `.sigil/`.
- **Sensitive Files:** Access to `.env`, `.ssh/`, and other sensitive paths is hard-blocked in `sigil/core/security.py`.
- **Rollback:** If post-hooks fail after all retries, the worktree is rolled back using `git checkout --`.
- **Worktree Isolation:** Worktrees are created with `git worktree add --no-track` to prevent automatic tracking of the base branch, ensuring clean isolation.
- **Failure Reason Guarantee:** The executor never returns `None` as `failure_reason`; a default message is always provided to avoid leaking `None` values into issue descriptions.
