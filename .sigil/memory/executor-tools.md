# Worktree-Based Parallel Execution with Pre/Post Hook Pipeline

## Tools

### read_file

Reads a file with pagination. Limits: 2000 lines, 50KB per read. If the first line at the requested offset exceeds 50KB (e.g. minified files, single-line JSON), returns a message suggesting `sed` + `head -c` instead.

### apply_edit

Find-and-replace with normalized fuzzy matching:
1. Exact match first
2. If not found, normalize both sides (smart quotes → ASCII, dashes → hyphen, special spaces → space, trailing whitespace stripped)
3. If still not found, fall back to sequence-matcher fuzzy matching (threshold 85%)
4. If still not found, report the best-match region for debugging

Detects no-op edits (old_content == new_content) and reports without writing.

### multi_edit

Atomic batch edit tool. Accepts a list of `{old_content, new_content}` edits. All matched against the **original** file content. Applied in reverse position order. Rejects overlapping edits. Supports the same normalized fuzzy fallback as `apply_edit`. Reports per-edit failure reasons.

### create_file

Creates a new file. Validates path is within the repo and not write-protected.

### grep

Searches file contents by regex pattern. Respects `.gitignore` and hidden directories.

### list_directory

Lists files and subdirectories. Respects hidden directory exclusions (`.git`, `.sigil`, `__pycache__`, `.ruff_cache`, `.pytest_cache`, `node_modules`).

### bash

Executes shell commands in a sandboxed environment. Timeout: 120 seconds. Working directory is the repo root.

## Safety Mechanisms

- **Path validation**: All file operations validate paths are within the repo
- **Write protection**: Certain files (`.sigil/working.md`, knowledge files) are write-protected
- **Sensitive file detection**: Prevents reading/writing files matching sensitive patterns
- **Edit failure limit**: After 3 consecutive edit failures, the agent loop terminates
- **Doom loop detection**: Repeated identical tool calls terminate the loop

## Removed Features

- `MAX_FULL_READS` (3) and `MAX_READS_HARD_STOP` (10) — removed. No hard cap on reads.
- `FileTracker.read_keys` and `FileTracker.read_totals` — removed. Read tracking simplified to `last_read` only.
- `reset_read_counters()` still exists but only resets `last_read`.
