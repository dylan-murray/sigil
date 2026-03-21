# Knowledge System — Sigil

## Overview

The knowledge system is Sigil's persistent brain. It compacts raw repository discovery into structured markdown files that downstream agents selectively load. This avoids re-reading the entire repo on every run and lets agents load only what's relevant to their task.

## Directory Structure

```
.sigil/memory/
├── INDEX.md          # Knowledge index — first thing agents read
├── working.md        # Operational history (managed by memory.py, not knowledge.py)
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

## Compaction Flow

`compact_knowledge(repo, model, discovery_context)`:

1. Load existing knowledge files (skip INDEX.md and working.md)
2. Build prompt with discovery context + existing files
3. LLM calls `write_knowledge_file` tool once per file
4. Each call writes the file to `.sigil/memory/`
5. After all files written, call `_generate_index()` to produce INDEX.md
6. INDEX.md gets `<!-- head: {sha} | updated: {timestamp} -->` prepended

### Budget System
```python
def _knowledge_budget(model: str) -> int:
    context_window = get_context_window(model)
    budget_tokens = max(context_window // 4, 4000)
    budget_chars = budget_tokens * 4
    return min(budget_chars, 200_000)
```

Total character budget for all knowledge files combined scales with model context window.

### Reserved Files
The LLM cannot write `INDEX.md` or `working.md` — these are managed separately. Attempts return an error message to the LLM.

## Knowledge Selection

`select_knowledge(repo, model, task_description)`:

1. Load INDEX.md
2. LLM reads index and calls `load_knowledge_files` tool with relevant filenames
3. Load and return the requested files as `{filename: content}` dict

```python
# tool_choice forces the LLM to call the tool
response = await litellm.acompletion(
    model=model,
    messages=[{"role": "user", "content": prompt}],
    tools=[SELECT_TOOL],
    tool_choice={"type": "function", "function": {"name": "load_knowledge_files"}},
    temperature=0.0,
    max_tokens=get_max_output_tokens(model),
)
```

If no INDEX.md exists (first run), returns `{}`.

## INDEX.md Format

```markdown
<!-- head: abc123def456 | updated: 2026-01-01T00:00:00Z -->

# Knowledge Index

## project.md
<thorough 3-5 line description of what's in this file and when to read it>

## architecture.md
<thorough description...>
```

The INDEX prompt instructs the LLM to write thorough multi-line descriptions — vague one-liners are explicitly rejected. The goal: an agent reading only INDEX.md should know exactly which files to load for any task.

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
    shutil.copytree(memory_src, memory_dst, dirs_exist_ok=True)
```

This gives each execution agent a consistent view of knowledge at branch creation time. Memory updates on the branch are discarded during rebase (main's version wins).

## Security

Knowledge files are committed to the repository and may be public. The compaction prompt explicitly warns:

> CRITICAL: These files are committed to the repository and may be public. NEVER include API keys, secrets, tokens, passwords, credentials, or any sensitive information.

The working memory prompt has the same warning.
