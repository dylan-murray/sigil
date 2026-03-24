# API Reference

## Core Data Structures

### Finding
```python
@dataclass(frozen=True)
class Finding:
    category: str       # "dead_code"|"tests"|"security"|"docs"|"types"|"todo"|"style"
    file: str           # Exact file path from project knowledge
    line: int | None    # Line number if known, None otherwise
    description: str    # Clear, specific problem description
    risk: str           # "low"|"medium"|"high"
    suggested_fix: str  # Concrete fix description
    disposition: str    # "pr"|"issue"|"skip"
    priority: int       # 1 = highest priority
    rationale: str      # One sentence explaining disposition/priority
```

### FeatureIdea
```python
@dataclass(frozen=True)
class FeatureIdea:
    title: str          # Short, specific title
    description: str    # Detailed feature description
    rationale: str      # Why this makes sense for THIS project
    complexity: str     # "small"|"medium"|"large"
    disposition: str    # "pr"|"issue"
    priority: int       # 1 = highest priority
```

### ExecutionResult
```python
@dataclass(frozen=True)
class ExecutionResult:
    success: bool               # Whether execution completed successfully
    diff: str                   # Git diff of changes made
    hooks_passed: bool          # Whether all hooks passed
    failed_hook: str | None     # Name of hook that failed, if any
    retries: int                # Number of retry attempts made
    failure_reason: str | None  # Reason for failure if success=False
    summary: str = ""           # LLM-provided summary of changes made
    downgraded: bool = False    # Whether downgraded to issue
    downgrade_context: str = "" # Context for downgrade decision
    failure_type: str | None = None  # Typed semantic failure category (see 063)
```

### ExistingIssue
```python
@dataclass(frozen=True)
class ExistingIssue:
    number: int         # GitHub issue number
    title: str          # Issue title
    body: str           # Issue body (truncated to 200 chars)
    labels: list[str]   # Issue labels
    is_open: bool       # Whether issue is open
    has_directive: bool # Whether issue has '@sigil work on this' directive
```

### Config
```python
@dataclass(frozen=True, slots=True)
class Config:
    model: str = "anthropic/claude-sonnet-4-6"
    boldness: Boldness = "bold"          # "conservative"|"balanced"|"bold"|"experimental"
    focus: list[str] = [...]             # Default: tests, dead_code, security, docs, types, features
    ignore: list[str] = []              # Glob patterns to ignore (currently unused in filtering)
    max_prs_per_run: int = 3
    max_issues_per_run: int = 5
    max_ideas_per_run: int = 15
    idea_ttl_days: int = 180
    pre_hooks: list[str] = []           # Commands to run before code generation (failure aborts)
    post_hooks: list[str] = []          # Commands to run after code generation (failure triggers retry)
    max_retries: int = 1
    max_parallel_agents: int = 3
    agents: dict[str, dict] = {}        # Per-agent model overrides
    fetch_github_issues: bool = True    # Whether to fetch existing issues
    max_github_issues: int = 25         # Max issues to fetch
    directive_phrase: str = "@sigil work on this"  # Phrase to scan for in issue comments
    validation_mode: str = "single"     # "single" or "parallel"
    max_cost_usd: float = 20.0          # Run budget cap
```

### GitHubClient
```python
def@dataclass
class GitHubClient:
    gh: Github          # PyGithub instance
    repo: GHRepo        # PyGithub repository object
```

### DedupResult
```python
@dataclass(frozen=True)
class DedupResult:
    skipped: list[WorkItem]     # Items that matched existing PRs/issues
    remaining: list[WorkItem]   # Items that passed dedup check
    reasons: dict[int, str]     # Index → reason for skipping
```

### ValidationResult
```python
@dataclass(frozen=True)
class ValidationResult:
    findings: list[Finding]
    ideas: list[FeatureIdea]
```

### WorkItem
```python
WorkItem = Union[Finding, FeatureIdea]
```

### TokenUsage
```python
@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, "TokenUsage"] = field(default_factory=dict)
```

### CallTrace
```python
@dataclass
class CallTrace:
    timestamp: str
    label: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
```

### _ChangeTracker (internal, executor.py)
```python
@dataclass
class _ChangeTracker:
    modified: set[str]   # Files modified via apply_edit
    created: set[str]    # Files created via create_file
```

## Public Functions by Module

### `cli.py`
```python
def run(repo: Path, dry_run: bool, model: str | None, trace: bool) -> None
# CLI entry point (sync wrapper around asyncio.run)
# Flags: --repo (default "."), --dry-run, --model, --trace

async def _run(repo: Path, dry_run: bool, model: str | None, trace: bool) -> None
# Main async pipeline
# Uses config.model_for("compactor") for compact_knowledge()
# Fetches existing issues if config.fetch_github_issues=true
# Passes existing issues to validate_all()
# Catches BudgetExceededError and exits with code 1
# Writes trace file if trace=true

def _format_run_context(
    findings: list[Finding],
    ideas: list[FeatureIdea],
    dry_run: bool,
    execution_results: list[tuple[str, ExecutionResult]] | None,
    pr_urls: list[str] | None,
    issue_urls: list[str] | None,
) -> str
# Format run summary for working memory update
```

### `config.py`
```python
Config.load(repo_path: Path) -> Config          # Load from .sigil/config.yml; returns defaults if missing
Config.to_yaml() -> str                          # Serialize to YAML string (for first-run creation)
Config.with_model(model: str) -> Config          # Return copy with different model

SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
DEFAULT_CHEAP_MODEL = "anthropic/claude-haiku-4-5-20251001"
CHEAP_MODEL_AGENTS = frozenset({"selector", "ideator", "compactor", "memory"})
Boldness = Literal["conservative", "balanced", "bold", "experimental"]
```

### `discovery.py`
```python
async def discover(repo: Path, model: str) -> str
# Returns raw discovery context string containing:
# - Name, language, CI, top-level dirs, file count
# - File listing (git ls-files, max 500)
# - README, CLAUDE.md content
# - Package manifest content
# - Recent commits (last 15)
# - Source file contents (budget-truncated, raw)
```

### `agent_config.py`
```python
async def detect_agent_configs(repo: Path) -> dict[str, str]
# Scans for known agent config files in priority order
# Returns {filename: content} for detected files
# Detects: AGENTS.md, CLAUDE.md, .cursorrules, .cursor/rules/*, .github/copilot-instructions.md, codex.md
# AGENTS.md takes highest priority; all others also ingested
# Bounded reads: respects file size limits, skips binary files
# Single-source detection: each file checked once
```

### `knowledge.py`
```python
async def compact_knowledge(repo: Path, model: str, discovery_context: str) -> str
# Writes knowledge files to .sigil/memory/, generates INDEX.md
# INIT mode: single LLM call → JSON with all files + index
# INCREMENTAL mode: git diff → read affected files → single LLM call → JSON with changed files + index
# Skips entirely (returns "") if HEAD matches INDEX.md (no new commits)
# Returns path to INDEX.md, or "" if nothing written

async def select_knowledge(repo: Path, model: str, task_description: str) -> dict[str, str]
# Returns {filename: content} for relevant knowledge files
# LLM reads INDEX.md and calls load_knowledge_files tool

async def is_knowledge_stale(repo: Path) -> bool
# True if INDEX.md missing or git HEAD doesn't match stored HEAD

def load_index(repo: Path) -> str
# Returns INDEX.md content or ""

def load_knowledge_file(repo: Path, filename: str) -> str
# Returns single knowledge file content or ""

def load_knowledge_files(repo: Path, filenames: list[str]) -> dict[str, str]
# Returns {filename: content} for requested files
```

### `memory.py`
```python
def load_working(repo: Path) -> str
# Returns working.md content or ""

async def update_working(repo: Path, model: str, run_context: str) -> str
# LLM compacts run context into working.md, returns new content
# Writes YAML frontmatter with last_updated timestamp
```

### `maintenance.py`
```python
async def analyze(repo: Path, config: Config) -> list[Finding]
# Returns up to 50 findings, sorted by priority
# Uses read_file tool (max 10 reads) to verify findings
# Reads working memory to avoid re-surfacing addressed findings
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization
```

### `ideation.py`
```python
async def ideate(repo: Path, config: Config) -> list[FeatureIdea]
# Returns deduplicated ideas from two temperature passes
# Returns [] if boldness == "conservative"
# Does NOT save to disk — caller must call save_ideas()
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization

def save_ideas(repo: Path, ideas: list[FeatureIdea]) -> list[Path]
# Writes ideas to .sigil/ideas/*.md with YAML frontmatter
# Returns list of written file paths
```

### `validation.py`
```python
async def validate_all(
    repo: Path,
    config: Config,
    findings: list[Finding],
    ideas: list[FeatureIdea],
    *,
    existing_issues: list[ExistingIssue] | None = None,
    on_status: StatusCallback | None = None,
) -> ValidationResult
# Unified LLM pass reviewing ALL candidates together
# Receives existing GitHub issues as context to avoid duplicating work
# Uses review_item tool with index (findings first, ideas offset by len(findings))
# Unreviewed findings → disposition="issue"; unreviewed ideas → kept as-is
# Checks [FILE EXISTS]/[FILE MISSING] tags for hallucination detection
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization
```

### `executor.py`
```python
async def execute(
    repo: Path, config: Config, item: WorkItem
) -> tuple[ExecutionResult, _ChangeTracker]
# Single-item execution on given repo path (no worktree management)
# LLM uses read_file/apply_edit/create_file/done tools
# read_file supports offset and limit params; capped at 2000 lines / 50KB
# Pre-hooks run before code generation; failure aborts
# Post-hooks run after code generation; failure triggers retry
# Uses prompt caching if model supports it
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization

async def execute_parallel(
    repo: Path, config: Config, items: list[WorkItem]
) -> list[tuple[WorkItem, ExecutionResult, str]]
# Parallel worktree execution
# Returns (item, result, branch) tuples; branch="" if worktree creation failed
# Cleans up failed worktrees immediately
```

### `github.py`
```python
async def create_client(repo: Path) -> GitHubClient | None
# Returns None if GITHUB_TOKEN not set or auth fails

async def ensure_labels(client: GitHubClient) -> None
# Creates "sigil" label if it doesn't exist

async def fetch_existing_issues(
    client: GitHubClient,
    *,
    max_issues: int = 25,
    directive_phrase: str = "@sigil work on this",
) -> list[ExistingIssue]
# Fetches open issues with 'sigil' label
# Scans issue comments for directive phrase (case-insensitive)
# Returns list of ExistingIssue with has_directive flag set
# Truncates issue body to 200 chars

async def dedup_items(client: GitHubClient, items: list[WorkItem]) -> DedupResult
# Checks open PRs, open issues, closed issues for title matches
# Three matching strategies: exact, category+file key, token similarity (Jaccard ≥ 0.6)

async def push_branch(repo: Path, branch: str) -> bool
# git push -u origin {branch}, returns success

async def open_pr(
    client: GitHubClient,
    item: WorkItem,
    result: ExecutionResult,
    branch: str,
    repo: Path,
) -> str | None
# Push branch + create PR, returns PR URL or None

async def open_issue(
    client: GitHubClient,
    item: WorkItem,
    downgrade_context: str | None = None,
) -> str | None
# Create GitHub issue, returns issue URL or None

async def publish_results(
    repo: Path,
    config,
    client: GitHubClient,
    execution_results: list[tuple[WorkItem, ExecutionResult, str]],
    issue_items: list[tuple[WorkItem, str | None]],
) -> tuple[list[str], list[str], set[str]]
# Returns (pr_urls, issue_urls, pushed_branches)
# Enforces max_prs_per_run and max_issues_per_run limits

async def cleanup_after_push(
    repo: Path,
    results: list[tuple[WorkItem, ExecutionResult, str]],
    pushed_branches: set[str] | None = None,
) -> None
# Removes worktrees + local branches for pushed branches
```

### `llm.py`
```python
async def acompletion(*, label: str = "unknown", **kwargs: Any) -> litellm.ModelResponse
# Async LLM call with exponential backoff retry
# Retries InternalServerError, RateLimitError, ServiceUnavailableError
# MAX_RETRIES=3, INITIAL_DELAY=1.0s, BACKOFF_FACTOR=2.0
# Records per-call trace with label, model, tokens, cost
# Checks budget after each call; raises BudgetExceededError if exceeded

def get_context_window(model: str) -> int
# Returns model's max input tokens (MODEL_OVERRIDES → litellm → fallback 32k)

def get_max_output_tokens(model: str) -> int
# Returns model's max output tokens (MODEL_OVERRIDES → litellm → fallback 8192)

def get_agent_output_cap(agent: str, model: str) -> int
# Returns per-agent output token cap (analyzer 16k, ideator 8k, validator 8k, codegen 32k)

def detect_doom_loop(messages: list[dict]) -> bool
# Returns True if last 3 tool calls are identical (same name + args)

def mask_old_tool_outputs(messages: list[dict], keep_recent: int = 10) -> None
# Replaces tool result content older than keep_recent with placeholders
# Modifies messages in-place; idempotent

async def compact_messages(messages: list[dict], model: str, threshold_tokens: int = 80000) -> None
# LLM summarizes old context when estimated tokens exceed threshold
# Modifies messages in-place; only triggers once per call

def supports_prompt_caching(model: str) -> bool
# Returns True if model supports prompt caching

def cacheable_message(model: str, content: str) -> dict
# Builds message with cache control if model supports it

def compute_call_cost(
    model: str,
    prompt_tok: int,
    completion_tok: int,
    cache_read_tok: int = 0,
    cache_creation_tok: int = 0,
) -> float
# Calculates cost including cache multipliers (write 1.25x, read 0.10x)
# Non-cached input = max(prompt_tok - cache_read_tok - cache_creation_tok, 0)

def set_budget(max_cost_usd: float) -> None
# Sets run budget cap; raises BudgetExceededError if exceeded
```

## Known Notes

- `ExecutionResult.failure_type` is a typed semantic category for structured failure analysis (see 063).
