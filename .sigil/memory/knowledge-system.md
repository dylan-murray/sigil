# Knowledge System — Sigil

## Overview

The knowledge system is Sigil's persistent brain. It compacts raw repository discovery into structured markdown files that downstream agents selectively load. This avoids re-reading the entire repo on every run and lets agents load only what's relevant to their task.

## Directory Structure

```
.sigil/memory/
├── INDEX.md          # Knowledge index — first thing agents read
├── working.md        # Operational history (managed by memory.py, NOT knowledge.py)
├── project.md        # What the project is, stack, how to build/test
├── architecture.md   # Modules, data flow, component responsibilities
├── patterns.md       # Coding conventions, naming, error handling
├── dependencies.md   # External deps, internal module graph
└── *.md              # Any other topic files (up to 150 total)
```

## Staleness Detection

Knowledge is considered stale when the git HEAD has changed since last compaction:

```python
async def is_knowledge_stale(repo: Path) -> bool:
    index_path = _memory_dir(repo) / INDEX_FILE
    if not index_path.exists():
        return True
    content = read_file(index_path)
    match = re.search(r"head:\s*([a-f0-9]+)", content)
    if not match:
        return True
    return match.group(1) != await get_head(repo)
```

INDEX.md stores the HEAD SHA in an HTML comment: `<!-- head: abc123 | updated: 2026-01-01T00:00:00Z -->`

**Skip optimization:** `compact_knowledge` checks HEAD at the start and returns `""` immediately if HEAD matches — zero LLM calls when nothing has changed.

## Compaction Flow (Two Modes)

`compact_knowledge(repo, model, discovery_context)` operates in two modes:

### INIT Mode (first run or no existing knowledge)

1. Check HEAD — if matches INDEX.md, return `""` immediately (no-op)
2. Build `INIT_PROMPT` with discovery context + existing knowledge files
3. Single `acompletion()` call — LLM returns one JSON object with all files + index
4. Parse response with `_parse_response()` (handles fences, truncation repair)
5. Write all files in one pass, skipping reserved names (`INDEX.md`, `working.md`)
6. Write INDEX.md with `<!-- head: {sha} | updated: {timestamp} -->` prepended

### INCREMENTAL Mode (existing knowledge + new commits)

1. Check HEAD — if matches, return `""` immediately
2. Run `git diff <last_head>..HEAD --name-only` to get changed source files
3. Run `git log <last_head>..HEAD --oneline` for commit summary
4. Fetch per-file diffs for changed files (capped at `MAX_DIFF_CHARS_PER_FILE` / `MAX_TOTAL_DIFF_CHARS`)
5. Build `INCREMENTAL_PROMPT` with commit log + diffs + current INDEX.md
6. LLM may call `read_knowledge_file` tool (up to `MAX_INCREMENTAL_ROUNDS = 3`) to load affected files
7. LLM returns single JSON object with only the changed files + full updated index
8. Write only the changed files; delete files where content is `""`
9. Write updated INDEX.md

### JSON Response Format

Both modes use the same structured JSON output (no tool loop for writing):

```json
{
  "files": {
    "project.md": "full markdown content...",
    "architecture.md": "full markdown content..."
  },
  "index": "# Knowledge Index\n\n## project.md\n<thorough description>\n\n..."
}
```

The `_parse_response()` helper strips markdown fences if present and falls back to `_repair_truncated_json()` if the response was truncated.

### Budget System

```python
def _knowledge_budget(model: str) -> int:
    context_window = get_context_window(model)
    budget_tokens = max(context_window // 4, 4000)
    budget_chars = budget_tokens * 4
    return min(budget_chars, 200_000)

def _max_input_chars(model: str) -> int:
    # How many chars can fit in the prompt (input side)
    available_tokens = get_context_window(model) - get_max_output_tokens(model) - PROMPT_OVERHEAD_TOKENS
    return available_tokens * CHARS_PER_TOKEN
```

### Reserved Files

The LLM cannot write `INDEX.md` or `working.md` — these are managed separately. Any such filenames in the JSON response are silently skipped.

### Return Value
- Returns path to INDEX.md as string if files were written
- Returns `""` if HEAD matched (no-op) or LLM returned no files

## Key Constants (knowledge.py)

```python
MAX_KNOWLEDGE_FILES = 150
RESERVED_FILES = frozenset({"INDEX.md", "working.md"})
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 2000
MAX_DIFF_CHARS_PER_FILE = 10_000
MAX_TOTAL_DIFF_CHARS = 100_000
MAX_INCREMENTAL_ROUNDS = 3      # Max read_knowledge_file tool calls in incremental mode
MAX_CONCURRENT_DIFFS = 20
MAX_TOOL_READ_CHARS = 100_000
```

Note: `MAX_LLM_ROUNDS = 10` is gone — replaced by `MAX_INCREMENTAL_ROUNDS = 3` (only for tool reads in incremental mode).

## Knowledge Selection

`select_knowledge(repo, model, task_description)` — unchanged from before:

1. Load INDEX.md
2. LLM reads index and calls `load_knowledge_files` tool with relevant filenames
3. Load and return the requested files as `{filename: content}` dict

```python
# tool_choice forces the LLM to call the tool
response = await acompletion(
    model=model,
    messages=[{"role": "user", "content": prompt}],
    tools=[SELECT_TOOL],
    tool_choice={"type": "function", "function": {"name": "load_knowledge_files"}},
    temperature=0.0,
    max_tokens=get_max_output_tokens(model),
)
```

If no INDEX.md exists (first run), returns `{}`.

## LLM Tools in knowledge.py

- **`load_knowledge_files`** (`SELECT_TOOL`) — `{filenames: list[str]}` — used in `select_knowledge`
- **`read_knowledge_file`** (`READ_KNOWLEDGE_TOOL`) — `{filename: str}` — used in incremental compaction so LLM can read existing files before updating them

Note: `write_knowledge_file` tool is **gone** — replaced by JSON response format.

## Per-Agent Model for Compaction

A separate model can be used for compaction via per-agent config:

```yaml
agents:
  compactor:
    model: anthropic/claude-haiku-4-5-20251001
```

```python
# In cli.py:
compact_model = config.model_for("compactor")
await compact_knowledge(resolved, compact_model, discovery_context)
```

This allows using a cheaper/faster model for knowledge compaction while using a stronger model for analysis and execution.

## INDEX.md Format

```markdown
<!-- head: abc123def456 | updated: 2026-01-01T00:00:00Z -->

# Knowledge Index

## project.md
<thorough 3-5 line description of what's in this file and when to read it>

## architecture.md
<thorough description...>
```

The index is now generated in the same LLM call as the knowledge files (not a separate call).

## Working Memory (memory.py)

`working.md` is separate from knowledge files — it tracks operational history:

```markdown
---
last_updated: 2026-01-01T00:00:00Z
---

## What Sigil Has Done
- Opened PR #42: fix dead_code in utils.py (merged)
- Filed issue #43: missing tests for github.py

## What Didn't Work
- Attempted to add type annotations to executor.py — tests failed after 3 retries

## Focus for Next Run
- executor.py still needs type annotations
- Consider adding integration tests
```

`update_working()` uses LLM to compact the existing working.md + new run context into a fresh working.md. Old run details fade into summaries. Target: under 100 lines.

## Ideas Storage (ideation.py)

Feature ideas are stored separately in `.sigil/ideas/`:

```markdown
---
title: Add retry logic to LLM calls
summary: Wrap litellm calls with exponential backoff
status: open
complexity: small
disposition: pr
priority: 1
created: 2026-01-01T00:00:00Z
---

# Add retry logic to LLM calls

## Description
...

## Rationale
...
```

TTL-based cleanup: ideas older than `idea_ttl_days` (default 180) are deleted when `_load_existing_ideas()` runs.

## Memory Snapshot in Worktrees

When creating a worktree for execution, the current `.sigil/memory/` is copied:

```python
memory_src = repo / ".sigil" / "memory"
if memory_src.exists():
    memory_dst = worktree_path / ".sigil" / "memory"
    memory_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(memory_src, memory_dst, dirs_exist_ok=True)
```

This gives each execution agent a consistent view of knowledge at branch creation time. Memory updates on the branch are discarded during rebase (main's version wins via `--ours`).

## Security

Knowledge files are committed to the repository and may be public. Both compaction prompts explicitly warn:

> CRITICAL: These files are committed to the repository and may be public. NEVER include API keys, secrets, tokens, passwords, credentials, or any sensitive information.

## Knowledge File Naming

- Lowercase, hyphens for multi-word names, `.md` extension
- Examples: `project.md`, `architecture.md`, `error-handling.md`
- Up to 150 files total
- `INDEX.md` and `working.md` are reserved and silently skipped if the LLM tries to write them
