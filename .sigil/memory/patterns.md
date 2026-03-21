# Coding Patterns — Sigil

## Python Standards

- **Python version:** 3.11+ (uses modern type hints throughout)
- **Union types:** PEP 604 syntax — `str | None`, not `Optional[str]`
- **Exceptions:** Specific types only — `OSError`, `ValueError`, `GithubException`; never bare `except:` or `except Exception:`
- **No comments:** Unless logic is genuinely non-obvious (hard project rule)
- **Line length:** 100 characters (ruff configured)
- **Quotes:** Double quotes (ruff configured)
- **Imports:** Standard library → third-party → local; no blank lines between groups within a section

## Naming Conventions

- **Functions/variables:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private helpers:** Leading underscore (`_helper_function`, `_ChangeTracker`)
- **Async wrappers:** `arun` wraps sync subprocess; `_run_llm_edits` is async LLM loop

## Dataclass Pattern

All domain objects are frozen dataclasses:

```python
@dataclass(frozen=True)
class Finding:
    category: str
    file: str
    line: int | None
    description: str
    risk: str
    suggested_fix: str
    disposition: str
    priority: int
    rationale: str
```

Use `dataclasses.replace()` to create modified copies (since frozen):
```python
validated.append(replace(finding, disposition=new_disp))
```

`Config` uses `slots=True` in addition to `frozen=True` for memory efficiency.

## Tool-Use Pattern (LLM Interactions)

All LLM interactions use structured tool calls — never parse raw text responses:

```python
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_finding",
        "description": "...",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["dead_code", "tests", ...]},
            },
            "required": ["category", "description"],
        },
    },
}

# Standard LLM loop pattern (used in maintenance, ideation, validation, knowledge, executor)
messages: list[dict] = [{"role": "user", "content": prompt}]
results = []

for _ in range(MAX_LLM_ROUNDS):  # MAX_LLM_ROUNDS = 10
    response = await litellm.acompletion(
        model=config.model,
        messages=messages,
        tools=[TOOL_SCHEMA],
        temperature=0.0,
        max_tokens=get_max_output_tokens(config.model),
    )
    choice = response.choices[0]

    if not choice.message.tool_calls:
        break

    messages.append(choice.message)  # ALWAYS append assistant message first

    for tool_call in choice.message.tool_calls:
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": "Invalid JSON."
            })
            continue

        # Process args, build result
        results.append(...)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": "Recorded."
        })

    if choice.finish_reason == "stop":
        break
```

**Key details:**
- Always append `choice.message` (the assistant message) before tool responses
- Tool response format: `{"role": "tool", "tool_call_id": ..., "content": ...}`
- `tool_choice` can force a specific tool: `{"type": "function", "function": {"name": "load_knowledge_files"}}`
- `MAX_LLM_ROUNDS = 10` is the standard cap across all agents

## Async Subprocess Pattern

Always use `arun()` from `utils.py`, never `subprocess.run`:

```python
# List form (preferred for safety — no shell injection)
rc, stdout, stderr = await arun(["git", "ls-files"], cwd=repo, timeout=10)

# Shell form (for pipes/complex commands)
rc, stdout, stderr = await arun("echo abc | tr a-z A-Z", timeout=5)

# Always check return code
if rc != 0:
    logger.warning("Command failed: %s", stderr.strip())
```

## Parallel Execution Pattern

```python
# Independent operations — use gather
findings, ideas = await asyncio.gather(
    analyze(repo, config),
    ideate(repo, config),
)

# Bounded concurrency — use Semaphore
sem = asyncio.Semaphore(config.max_parallel_agents)

async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
    async with sem:
        return await _execute_in_worktree(repo, config, item, slug)

results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))
```

## GitHub API Pattern

PyGithub is synchronous — always wrap with `asyncio.to_thread`:

```python
def _sync_operation(client: GitHubClient) -> str:
    return client.repo.create_pull(title=..., body=..., head=..., base=...)

result = await asyncio.to_thread(_sync_operation, client)
```

Rate limiting via tenacity decorator (applied to sync functions before `to_thread`):
```python
_gh_retry = retry(
    retry=retry_if_exception(lambda e: isinstance(e, GithubException) and e.status in (403, 429)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)

@_gh_retry
def _create_pull(client, title, body, branch):
    ...
```

## Path Safety Pattern

All file operations in executor validate paths against repo root:

```python
def _validate_path(repo: Path, file: str) -> Path | None:
    try:
        resolved = (repo / file).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(repo.resolve()):
        return None
    return resolved
```

Always call `_validate_path` before any file read/write in executor tools. Returns `None` for traversal attempts or absolute paths.

## Configuration Loading Pattern

```python
@classmethod
def load(cls, repo_path: Path) -> "Config":
    config_path = repo_path / SIGIL_DIR / CONFIG_FILE
    if not config_path.exists():
        return cls()  # Return defaults
    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {CONFIG_FILE}: {e}") from e
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_FILE} must be a YAML mapping, got {type(raw).__name__}")
    raw.pop("version", None)  # Strip version field
    unknown = set(raw) - set(cls.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Unknown field(s) in {CONFIG_FILE}: {', '.join(sorted(unknown))}")
    return cls(**raw)
```

## Memory/Knowledge File Pattern

Knowledge files live in `.sigil/memory/`. Always use `read_file()` from utils:

```python
def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""
```

Never use `path.read_text()` directly in knowledge/memory code — always go through `read_file()`.

## Error Handling Philosophy

- **User-facing errors:** Clear, actionable messages with context
- **LLM failures:** Log warning, continue (don't crash the run)
- **GitHub failures:** Log warning, graceful degradation
- **Subprocess failures:** Check `rc != 0`, log stderr
- **File not found:** Return empty string, not exception
- **Missing GITHUB_TOKEN in live mode:** Fail fast with clear error (not silent degradation)

## Import Organization

```python
# Standard library
import asyncio
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Annotated, Literal, Union

# Third-party
import litellm
import typer
import yaml
from github import Github, GithubException
from rich.console import Console
from tenacity import retry, stop_after_attempt

# Local
from sigil.config import Config, SIGIL_DIR
from sigil.utils import arun, read_file
```

## Slug/Branch Naming

```python
def _slugify(item: WorkItem) -> str:
    if isinstance(item, Finding):
        raw = f"{item.category}-{Path(item.file).stem}"
    else:
        raw = item.title
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:50]

def _branch_name(slug: str) -> str:
    return f"sigil/auto/{slug}-{int(time.time())}"
```

Collision handling in `_dedup_slugs()`: append `-1`, `-2`, etc. to duplicate slugs.

## Prompt Structure

All prompts follow this structure:
1. Role declaration ("You are Sigil, an autonomous repo improvement agent...")
2. Task description with boldness/focus context
3. Knowledge context (from `select_knowledge()`)
4. Working memory (from `load_working()`)
5. Tool instructions ("Use the X tool for each Y...")
6. Rules section (numbered constraints)

## Validation Item Indexing

In `validate_all()`, items are indexed as a flat list: findings first (indices 0..N-1), then ideas (indices N..N+M-1). The `review_item` tool uses this flat index. The offset is `len(findings)`.

```python
# In _format_items():
for i, f in enumerate(findings):
    lines.append(f"[{i}] ...")
offset = len(findings)
for j, idea in enumerate(ideas):
    idx = offset + j
    lines.append(f"[{idx}] ...")
```
