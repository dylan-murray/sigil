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
    downgraded: bool            # Whether downgraded to issue (default False)
    downgrade_context: str      # Context for downgrade decision (default "")
```

### Config
```python
@dataclass(frozen=True, slots=True)
class Config:
    model: str                  # LLM model string (litellm format)
    boldness: Boldness          # "conservative"|"balanced"|"bold"|"experimental"
    focus: list[str]            # Areas to analyze
    ignore: list[str]           # Glob patterns to ignore
    max_prs_per_run: int        # Default 3
    max_issues_per_run: int     # Default 5
    max_ideas_per_run: int      # Default 15
    idea_ttl_days: int          # Default 180
    lint_cmd: str | None        # Custom lint command
    test_cmd: str | None        # Custom test command
    max_retries: int            # Default 3
    max_parallel_agents: int    # Default 3
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

### WorkItem
```python
WorkItem = Union[Finding, FeatureIdea]
```

## Public Functions by Module

### `cli.py`
```python
# CLI entry point (sync wrapper)
def run(repo: Path, dry_run: bool, model: str | None) -> None

# Main async pipeline
async def _run(repo: Path, dry_run: bool, model: str | None) -> None

# Format run summary for working memory
def _format_run_context(
    findings: list[Finding],
    ideas: list[FeatureIdea],
    dry_run: bool,
    execution_results: list[tuple[str, ExecutionResult]] | None,
    pr_urls: list[str] | None,
    issue_urls: list[str] | None,
) -> str
```

### `config.py`
```python
Config.load(repo_path: Path) -> Config          # Load from .sigil/config.yml
Config.to_yaml() -> str                          # Serialize to YAML string
Config.with_model(model: str) -> Config          # Return copy with different model

SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
```

### `discovery.py`
```python
async def discover(repo: Path, model: str) -> str
# Returns raw discovery context string with:
# - Name, language, CI, top-level dirs, file count
# - File listing (git ls-files, max 500)
# - README, CLAUDE.md content
# - Package manifest content
# - Recent commits (last 15)
# - Source file contents (budget-truncated)
```

### `knowledge.py`
```python
async def compact_knowledge(repo: Path, model: str, discovery_context: str) -> str
# Writes knowledge files to .sigil/memory/, generates INDEX.md
# Returns path to INDEX.md, or "" if nothing written

async def select_knowledge(repo: Path, model: str, task_description: str) -> dict[str, str]
# Returns {filename: content} for relevant knowledge files

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
```

### `maintenance.py`
```python
async def analyze(repo: Path, config: Config) -> list[Finding]
# Returns up to 50 findings, sorted by priority
# Reads working memory to avoid re-surfacing addressed findings
```

### `ideation.py`
```python
async def ideate(repo: Path, config: Config) -> list[FeatureIdea]
# Returns deduplicated ideas from two temperature passes
# Returns [] if boldness == "conservative"

async def validate_ideas(
    repo: Path, config: Config, ideas: list[FeatureIdea]
) -> list[FeatureIdea]
# LLM reviews each idea: approve/adjust/veto

def save_ideas(repo: Path, ideas: list[FeatureIdea]) -> list[Path]
# Writes ideas to .sigil/ideas/*.md with YAML frontmatter
```

### `validation.py`
```python
async def validate(
    repo: Path, config: Config, findings: list[Finding]
) -> list[Finding]
# LLM reviews each finding: approve/adjust/veto
# Unreviewed findings default to disposition="issue"
```

### `executor.py`
```python
async def execute(repo: Path, config: Config, item: WorkItem) -> ExecutionResult
# Single-item execution on current branch (no worktree)
# LLM uses read_file/apply_edit/create_file/done tools
# Lint → test → retry loop

async def execute_parallel(
    repo: Path, config: Config, items: list[WorkItem]
) -> list[tuple[WorkItem, ExecutionResult, str]]
# Parallel worktree execution, returns (item, result, branch) tuples
# branch="" if worktree creation failed
```

### `github.py`
```python
async def create_client(repo: Path) -> GitHubClient | None
# Returns None if GITHUB_TOKEN not set or auth fails

async def ensure_labels(client: GitHubClient) -> None
# Creates "sigil" label if it doesn't exist

async def dedup_items(client: GitHubClient, items: list[WorkItem]) -> DedupResult
# Checks open PRs, open issues, closed issues for title matches

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
    config: Config,
    client: GitHubClient,
    execution_results: list[tuple[WorkItem, ExecutionResult, str]],
    issue_items: list[tuple[WorkItem, str | None]],
) -> tuple[list[str], list[str], set[str]]
# Returns (pr_urls, issue_urls, pushed_branches)

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
# Returns model's max input tokens (with MODEL_OVERRIDES fallback)

def get_max_output_tokens(model: str) -> int
# Returns model's max output tokens (with MODEL_OVERRIDES fallback)
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
# Handles timeout, FileNotFoundError gracefully

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
- **`report_finding`** — `{category, file, line?, description, risk, suggested_fix, disposition, priority, rationale}` — used in `analyze`
- **`report_idea`** — `{title, description, rationale, complexity, disposition, priority}` — used in `ideate`

### Validation Tools
- **`validate_finding`** — `{finding_index, action, new_disposition?, reason}` — used in `validate`
- **`review_idea`** — `{idea_index, action, new_disposition?, reason}` — used in `validate_ideas`

### Executor Tools
- **`read_file`** — `{file: str}` — read file content
- **`apply_edit`** — `{file, old_content, new_content}` — surgical find-and-replace
- **`create_file`** — `{file, content}` — create new file
- **`done`** — `{summary: str}` — signal completion

## Constants

```python
# executor.py
MAX_TOOL_CALLS_PER_PASS = 15
COMMAND_TIMEOUT = 120
OUTPUT_TRUNCATE_CHARS = 4000
WORKTREE_DIR = ".sigil/worktrees"

# knowledge.py
MAX_KNOWLEDGE_FILES = 150
MAX_LLM_ROUNDS = 10  # (shared across all agents)

# discovery.py
MAX_FILE_LIST = 500
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000

# github.py
SIGIL_LABEL = "sigil"
SIGIL_LABEL_COLOR = "7B68EE"
```
