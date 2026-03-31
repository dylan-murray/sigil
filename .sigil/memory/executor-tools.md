# Executor Tools — Worktree-Based Parallel Execution with Pre/Post Hook Pipeline

The executor agent (`sigil/pipeline/executor.py`) uses a specific set of tools to modify the codebase safely.

## Tools
- **`read_file`:** Reads file content with pagination (2000 line / 50KB limit).
- **`apply_edit`:** Surgical find-and-replace. Requires an exact match of `old_content` to ensure the agent has read the latest version.
- **`multi_edit`:** Applies multiple sequential edits to a single file atomically.
- **`create_file`:** Creates new files (fails if the file already exists).
- **`grep`:** Searches the codebase using regex to find callers and imports.
- **`list_directory`:** Lists files and subdirectories in a given path.
- **`task_progress`:** A mandatory final tool where the agent must provide a 200+ character summary of changes.

## Safety Mechanisms
- **Write Protection:** The agent is blocked from modifying any files inside `.sigil/`.
- **Sensitive Files:** Access to `.env`, `.ssh/`, and other sensitive paths is hard-blocked in `sigil/core/security.py`.
- **Rollback:** If post-hooks fail after all retries, the worktree is rolled back using `git checkout --`.
