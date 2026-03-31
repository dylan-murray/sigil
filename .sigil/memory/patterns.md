# Sigil's Coding Patterns — Python Standards, Naming, and Framework Usage

## Python Standards

- **Python version:** 3.11+ (uses modern type hints throughout)
- **Union types:** PEP 604 syntax — `str | None`, not `Optional[str]`
- **Exceptions:** Specific types only — `OSError`, `ValueError`, `GithubException`; never bare `except:` or `except Exception:`
- **No comments:** Unless logic is genuinely non-obvious (hard project rule)
- **Line length:** 100 characters (ruff configured)
- **Quotes:** Double quotes (ruff configured)
- **Imports:** Standard library → third-party → local; no blank lines between groups within a section
- **Subpackage imports:** Use full paths like `from sigil.core.config import Config`, `from sigil.pipeline.executor import execute`

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
    implementation_spec: str = ""  # Concrete spec from validation
```

Use `dataclasses.replace()` to create modified copies (since frozen):
```python
validated.append(replace(finding, disposition=new_disp, implementation_spec=spec))
```

`Config` uses `slots=True` in addition to `frozen=True` for memory efficiency.

## Agent Framework — Tool and Agent Class Patterns

### Tool Class Pattern

All tools are defined as `Tool` objects. Each tool is self-contained: name, description, parameters, and handler in one object.

```python
from sigil.core.agent import Tool, ToolResult

async def _read_file_handler(args: dict) -> ToolResult:
    file_path = str(args.get("file", ""))
    content = read_file(file_path)
    return ToolResult(content=content)

read_tool = Tool(
    name="read_file",
    description="Read the full content of a file.",
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Path to read"},
        },
        "required": ["file"],
    },
    handler=_read_file_handler,
)
```

**Key details:**
- `Tool.schema()` renders OpenAI-format tool schema automatically
- Handler returns `ToolResult(content=..., stop=False, result=None)` or just a string
- `stop=True` exits the agent loop immediately
- `result` field carries structured data to the caller (e.g., summary from `done` tool)
- Tool objects are passed to `Agent(tools=[...])` at construction
- The `Agent` class auto-renders schemas for the LLM and dispatches by name

### Agent Class Pattern

All agents use the `Agent` class. The agent is a class with config + loop in one object.

```python
from sigil.core.agent import Agent, Tool

agent = Agent(
    label="analysis",
    model="anthropic/claude-sonnet-4-6",
    tools=[read_tool, report_tool],
    system_prompt="You are Sigil, an autonomous repo improvement agent...",
    temperature=0.0,
    max_rounds=10,
    use_cache=True,
    enable_doom_loop=True,
    enable_masking=True,
    enable_compaction=True,
)

result = await agent.run(
    context={
        "task": task_desc,
        "repo_conventions": repo_conventions # Injected via string.Template.safe_substitute
    },
    on_status=on_status,
)

# result: AgentResult(messages, doom_loop, rounds, stop_result, last_content)
```

**Key details:**
- `context` dict is injected into `system_prompt` via `$variable` placeholders
- `max_tokens` is used to set the maximum output tokens for the LLM call.
- `enable_doom_loop`, `enable_masking`, `enable_compaction` can be disabled per-agent
- `on_truncation` callback handles consecutive truncations (executor uses this)
- `mcp_mgr` and `extra_tool_schemas` for MCP tool integration
- `run()` returns `AgentResult` with full conversation history and metadata
- **Handoffs:** Programmatic, not LLM-driven. Pipeline decides next agent:
  ```python
  exec_result = await executor.run(context={"task": task_desc})
  test_result = await test_agent.run(context={"diff": diff})
  ```

## Async Subprocess Pattern

Always use `arun()` from `sigil.core.utils`, never `subprocess.run`:

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
sem = asyncio.Semaphore(config.max_parallel_tasks)

async def _run(item: WorkItem, slug: str) -> tuple[WorkItem, ExecutionResult, str]:
    async with sem:
        return await _execute_in_worktree(repo, config, item, slug)

results = list(await asyncio.gather(*[_run(item, slug) for item, slug in zip(items, slugs)]))
```

## GitHub API Pattern

PyGithub is synchronous — always wrap with `asyncio.to_thread`:

```python
from sigil.integrations.github import GitHubClient

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
def validate_path(repo: Path, file: str, ignore: list[str] | None = None) -> Path | None:
    if is_sensitive_file(file):
        return None
    if ignore and any(fnmatch(file, p) for p in ignore):
        return None
    try:
        resolved = (repo / file).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(repo.resolve()):
        return None
    return resolved
```

Always call `validate_path` before any file read/write in executor tools. Returns `None` for traversal attempts or absolute paths.

## Write Protection Pattern

The `.sigil/` directory is write-protected. Executor tools check this before any write:

```python
WRITE_PROTECTED_PATHS: tuple[str, ...] = (".sigil/")

def is_write_protected(file: str) -> bool:
    normalized = file.replace("\\", "/")
    return any(normalized.startswith(p) or f"/{p}" in normalized for p in WRITE_PROTECTED_PATHS)

# In _apply_edit and _create_file:
if is_write_protected(file):
    return f"Access denied: {file} is managed by Sigil and cannot be modified."
```

This prevents agents from accidentally modifying memory, config, or other Sigil-managed files.

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

Knowledge files live in `.sigil/memory/`. Always use `read_file()` from `sigil.core.utils`:

```python
from sigil.core.utils import read_file

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
- **LLM failures:** Log warning, continue (don't crash the run); `acompletion` retries automatically
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

# Local — use subpackage paths
from sigil.core.config import Config, SIGIL_DIR
from sigil.core.utils import arun, read_file
from sigil.core.agent import Agent, Tool, ToolResult  # Agent framework imports
from sigil.pipeline.executor import execute
from sigil.integrations.github import create_client
```

## Slug/Branch Naming

```python
def slugify(item: WorkItem) -> str:
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
3. Knowledge context (from `select_memory()`)
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

## Review Decisions Type

Validation decisions are stored as `ReviewDecision` objects:

```python
@dataclass(frozen=True)
class ReviewDecision:
    action: str
    new_disposition: str | None
    reason: str
    spec: str = ""
    relevant_files: list[str] | None = None
    priority: int = 99
```

When merging decisions from multiple reviewers, specs are preserved and merged appropriately.
