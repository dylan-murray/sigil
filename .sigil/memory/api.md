# API Reference — Core Data Structures, Public Functions, and Tool Schemas

## Core Data Structures

### Config (`sigil/core/config.py`)

```python
@dataclass(frozen=True, slots=True)
class Config:
    model: str = "ollama_chat/deepseek-v4-flash:cloud"
    boldness: str = "experimental"
    max_prs_per_run: int = 20
    max_github_issues: int = 0
    max_ideas_per_run: int = 100
    idea_ttl_days: int = 180
    max_retries: int = 3
    llm_timeout: int = 300
    max_parallel_tasks: int = 5
    agents: dict[str, list[dict]] = field(default_factory=dict)
    directive_phrase: str = "@sigil work on this"
    max_spend_usd: float = 20.0
    mcp_servers: list[dict] = field(default_factory=list)
    model_overrides: dict[str, dict[str, int]] = field(default_factory=dict)
```

Key methods:
- `instances_for(agent: str) -> list[AgentSpec]` — returns all configured instances for an agent
- `model_for(agent: str) -> str` — model of first instance
- `max_iterations_for(agent: str) -> int` — max iterations of first instance
- `max_tokens_for(agent: str) -> int | None` — max tokens of first instance
- `reasoning_effort_for(agent: str) -> str | None` — reasoning effort of first instance
- `load(repo: Path) -> Config` — load from `.sigil/config.yml`

### AgentSpec (`sigil/core/config.py`)

```python
@dataclass(frozen=True, slots=True)
class AgentSpec:
    model: str
    max_tokens: int | None
    max_iterations: int
    reasoning_effort: str | None
```

### FeatureIdea (`sigil/pipeline/models.py`)

```python
@dataclass
class FeatureIdea:
    title: str
    description: str
    rationale: str
    complexity: str  # "small" | "medium" | "large"
    disposition: str  # "pr" | "issue" | "skip"
    priority: int = 99
    implementation_spec: str = ""
    relevant_files: tuple[str, ...] = ()
    boldness: str = "balanced"
    generated_by: str = ""  # model that generated this idea
```

### Finding (`sigil/pipeline/maintenance.py`)

```python
@dataclass
class Finding:
    category: str
    file: str
    description: str
    triage: str  # "pr" | "issue" | "skip"
    line: int = 0
    severity: str = "medium"
    code_snippet: str = ""
    relevant_files: tuple[str, ...] = ()
```

### FileTracker (`sigil/pipeline/models.py`)

```python
@dataclass
class FileTracker:
    modified: set[str]
    created: set[str]
    last_read: dict[str, datetime]
    file_contents: dict[str, str]
    file_lines: dict[str, list[str]]
```

Note: `read_keys` and `read_totals` have been removed from `FileTracker`.

### Agent (`sigil/core/agent.py`)

```python
@dataclass
class Agent:
    label: str
    model: str
    tools: list[Tool]
    system_prompt: str = ""
    max_rounds: int = 15
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    enable_masking: bool = True
    enable_compaction: bool = True
    mcp_mgr: MCPManager | None = None
    extra_tool_schemas: list[dict] | None = None
```

### Tool (`sigil/core/agent.py`)

```python
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], Awaitable[ToolResult]]
```

### ToolResult (`sigil/core/agent.py`)

```python
@dataclass
class ToolResult:
    content: str = ""
    stop: bool = False
    result: Any = None
```

## Public Functions by Module

### sigil/core/config.py

- `Config.load(repo: Path) -> Config`
- `Config.model_for(agent: str) -> str`
- `Config.instances_for(agent: str) -> list[AgentSpec]`
- `Config.max_iterations_for(agent: str) -> int`
- `Config.max_tokens_for(agent: str) -> int | None`
- `Config.reasoning_effort_for(agent: str) -> str | None`

### sigil/core/tools.py

- `make_read_file_tool(repo, tracker, ignore) -> Tool`
- `make_apply_edit_tool(repo, tracker, ignore) -> Tool`
- `make_multi_edit_tool(repo, tracker, ignore) -> Tool`
- `make_create_file_tool(repo, tracker, ignore) -> Tool`
- `make_grep_tool(repo, on_status, ignore) -> Tool`
- `make_list_dir_tool(repo, on_status, ignore) -> Tool`
- `make_bash_tool(repo, on_status) -> Tool`
- `make_finalize_tool() -> Tool`
- `paginate_lines(lines, offset, limit, file_path) -> str`
- `paginate_content(content, offset, limit, file_path) -> str`
- `normalize_for_fuzzy_match(text) -> str`

### sigil/core/utils.py

- `normalize_for_fuzzy_match(text: str) -> str` — NFKC + smart-quote/dash/space → ASCII
- `fuzzy_find_match(content, old_content) -> tuple[str, float, int] | None`
- `find_all_match_locations(content, pattern) -> list[int]`
- `format_ambiguous_matches(content, matched_text, file) -> str`
- `find_best_match_region(content, old_content) -> str`
- `read_file(path) -> str`
- `fix_double_escaped(text) -> str`
- `numbered_window(lines, center, context) -> str`

### sigil/pipeline/ideation.py

- `ideate(repo, config, on_status) -> list[FeatureIdea]`
- `load_open_ideas(repo, ttl_days) -> list[FeatureIdea]`

### sigil/pipeline/validation.py

- `validate_all(repo, config, findings, ideas, on_status) -> ValidationResult`

### sigil/pipeline/executor.py

- `execute(repo, config, items, on_status) -> list[ExecutionResult]`
- `execute_parallel(repo, config, items, slugs, *, gh_client, models_section, on_pr_published, on_issue_downgrade, ...) -> list[tuple[WorkItem, ExecutionResult, str]]`

### sigil/integrations/github.py

- `create_client() -> GitHubClient`
- `dedup_items(client, items) -> DedupResult`
- `ensure_labels(client) -> None`
- `fetch_existing_issues(client) -> list[ExistingIssue]`
- `format_models_used(config) -> str` — generates "Models Used" section for PR bodies (was `_format_models_used`)
- `open_pr(client, item, result, branch, repo, *, summary_model, models_section) -> str | None`
- `open_issue(client, item, downgrade_context) -> str | None`
- `publish_issues(client, issue_items, *, max_issues) -> list[str]` — opens GitHub issues for a list of `(WorkItem, context)` tuples

## Constants

- `AGENT_NAMES`: `{"architect", "engineer", "auditor", "ideator", "triager", "selector", "reviewer", "compactor", "memory", "tool", "discovery"}`
- `MAX_READ_LINES`: 2000
- `MAX_READ_BYTES`: 50_000
- `MAX_EDIT_FAILURES`: 3
- `EDIT_CONTEXT_LINES`: 10
- `FUZZY_THRESHOLD`: 0.85

## Removed

- `Config.arbiter` field — removed
- `challenger` agent — removed
- `arbiter` agent — removed
- `FileTracker.read_keys` — removed
- `FileTracker.read_totals` — removed
- `MAX_FULL_READS` constant — removed
- `MAX_READS_HARD_STOP` constant — removed
- `publish_results()` — removed; PRs now published inline in executor, issues via `publish_issues()`
- `cleanup_after_push()` — removed; cleanup now happens inline in `_publish_and_cleanup()`
- `_format_models_used()` — renamed to `format_models_used()` (made public)
