# API Reference — Sigil

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
    lint_passed: bool           # Whether lint checks passed
    tests_passed: bool          # Whether tests passed
    retries: int                # Number of retry attempts made
    failure_reason: str | None  # Reason for failure if success=False
    summary: str = ""           # LLM-provided summary of changes made
    downgraded: bool = False    # Whether downgraded to issue
    downgrade_context: str = "" # Context for downgrade decision
```

### Config
```python
@dataclass(frozen=True, slots=True)
class Config:
    model: str = "anthropic/claude-sonnet-4-6"
    boldness: Boldness = "bold"          # "conservative"|"balanced"|"bold"|"experimental"
    focus: list[str] = [...]             # Default: tests, dead_code, security, docs, types, features
    ignore: list[str] = []              # Glob patterns to ignore
    max_prs_per_run: int = 3
    max_issues_per_run: int = 5
    max_ideas_per_run: int = 15
    idea_ttl_days: int = 180
    lint_cmd: str | None = None         # Custom lint command (None = auto-detect)
    test_cmd: str | None = None         # Custom test command (None = auto-detect)
    max_retries: int = 3
    max_parallel_agents: int = 3
```

### GitHubClient
```python
@dataclass
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
def run(repo: Path, dry_run: bool, model: str | None) -> None
# CLI entry point (sync wrapper around asyncio.run)
# Flags: --repo (default "."), --dry-run, --model

async def _run(repo: Path, dry_run: bool, model: str | None) -> None
# Main async pipeline

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

### `knowledge.py`
```python
async def compact_knowledge(repo: Path, model: str, discovery_context: str) -> str
# Writes knowledge files to .sigil/memory/, generates INDEX.md
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
```

### `ideation.py`
```python
async def ideate(repo: Path, config: Config) -> list[FeatureIdea]
# Returns deduplicated ideas from two temperature passes
# Returns [] if boldness == "conservative"
# Does NOT save to disk — caller must call save_ideas()

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
) -> ValidationResult
# Unified LLM pass reviewing ALL candidates together
# Uses review_item tool with index (findings first, ideas offset by len(findings))
# Unreviewed findings → disposition="issue"; unreviewed ideas → kept as-is
# Checks [FILE EXISTS]/[FILE MISSING] tags for hallucination detection
```

### `executor.py`
```python
async def execute(
    repo: Path, config: Config, item: WorkItem
) -> tuple[ExecutionResult, _ChangeTracker]
# Single-item execution on given repo path (no worktree management)
# LLM uses read_file/apply_edit/create_file/done tools
# Lint → test → retry loop; rollback on failure

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
def get_context_window(model: str) -> int
# Returns model's max input tokens (MODEL_OVERRIDES → litellm → fallback 32k)

def get_max_output_tokens(model: str) -> int
# Returns model's max output tokens (MODEL_OVERRIDES → litellm → fallback 8192)

MODEL_OVERRIDES: dict[str, dict[str, int]]
# Hardcoded correct values for models where litellm info is stale
```

### `utils.py`
```python
async def arun(
    cmd: str | list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30,
) -> tuple[int, str, str]
# Returns (returncode, stdout, stderr)
# String → shell; list → exec
# Handles timeout (kills process), FileNotFoundError gracefully

async def get_head(repo: Path) -> str
# Returns current git HEAD SHA or ""

def now_utc() -> str
# Returns ISO 8601 UTC timestamp: "2026-01-01T00:00:00Z"

def read_file(path: Path) -> str
# Returns file content or "" if missing/unreadable
```

## LLM Tool Schemas

### Knowledge Tools
- **`write_knowledge_file`** — `{filename: str, content: str}` — used in `compact_knowledge`
- **`load_knowledge_files`** — `{filenames: list[str]}` — used in `select_knowledge`

### Analysis Tools
- **`read_file`** (maintenance) — `{file: str}` — verify findings against source
- **`report_finding`** — `{category, file, line?, description, risk, suggested_fix, disposition, priority, rationale}` — used in `analyze`
- **`report_idea`** — `{title, description, rationale, complexity, disposition, priority}` — used in `ideate`

### Validation Tool
- **`review_item`** — `{index: int, action: "approve"|"adjust"|"veto", new_disposition?: str, reason: str}` — used in `validate_all`
  - `index` is zero-based across combined list (findings first, then ideas)

### Executor Tools
- **`read_file`** — `{file: str}` — read file content
- **`apply_edit`** — `{file, old_content, new_content}` — surgical find-and-replace (exact match required, must be unique)
- **`create_file`** — `{file, content}` — create new file (fails if exists)
- **`done`** — `{summary: str}` — signal completion, exits tool loop

## Constants

```python
# executor.py
MAX_TOOL_CALLS_PER_PASS = 15
COMMAND_TIMEOUT = 120          # seconds for lint/test commands
OUTPUT_TRUNCATE_CHARS = 4000   # error output truncated before sending to LLM
WORKTREE_DIR = ".sigil/worktrees"

# knowledge.py
MAX_KNOWLEDGE_FILES = 150
MAX_LLM_ROUNDS = 10            # shared cap across all agents

# maintenance.py
MAX_FILE_READS = 10            # max read_file calls per analysis run
MAX_FILE_CHARS = 8000          # truncation for read_file responses

# discovery.py
MAX_FILE_LIST = 500
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000

# github.py
SIGIL_LABEL = "sigil"
SIGIL_LABEL_COLOR = "7B68EE"
SIMILARITY_THRESHOLD = 0.6     # Jaccard similarity for fuzzy dedup

# ideation.py
IDEAS_DIR = "ideas"
TEMP_RANGES = {
    "balanced": (0.1, 0.5),
    "bold": (0.2, 0.7),
    "experimental": (0.3, 0.9),
}
```

## Known Issues / Gaps

- `execute_parallel` uses `""` as sentinel for "no branch" — should be `str | None`
- `apply_edit` has no guard against empty `old_content` (potential unintended full-file replacement)
- `MODEL_OVERRIDES` in `llm.py` may be dead code (no tests for `llm.py`)
- `DEFAULT_MODEL` in `config.py` (`anthropic/claude-sonnet-4-6`) doesn't match `configuration.md` (which shows `anthropic/claude-sonnet-4-20250514`)
- Integration test directory is empty — no tests for GitHub API, LLM calls, or git worktree ops
