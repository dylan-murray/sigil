# API Reference — Core Data Structures, Public Functions, and Tool Schemas

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
    implementation_spec: str = ""  # Concrete spec for executor (from validation)
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
    implementation_spec: str = ""  # Concrete spec for executor (from validation)
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

### Instructions
```python
@dataclass(frozen=True)
class Instructions:
    detected_files: tuple[str, ...]  # List of detected config files
    source: str                       # Human-readable source name (e.g., "AGENTS.md (universal)")
    content: str                      # Concatenated content of all detected files
    
    @property
    def has_instructions(self) -> bool:
        return bool(self.content)
    
    def format_for_prompt(self) -> str:
        # Returns formatted string for agent prompts
    
    def format_for_pr_body(self) -> str:
        # Returns formatted string for PR descriptions
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
    max_tool_calls: int = 50            # Max tool calls per executor pass (default 50)
    agents: dict[str, dict] = {}        # Per-agent model overrides
    fetch_github_issues: bool = True    # Whether to fetch existing issues
    max_github_issues: int = 25         # Max issues to fetch
    directive_phrase: str = "@sigil work on this"  # Phrase to scan for in issue comments
    validation_mode: str = "single"     # "single" or "parallel"
    max_cost_usd: float = 20.0          # Run budget cap
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
# Flags: --repo (default "."), --dry-run, --model, --trace, --refresh

async def _run(repo: Path, dry_run: bool, model: str | None, trace: bool) -> None
# Main async pipeline
# Uses config.model_for("compactor") for compact_knowledge()
# Fetches existing issues if config.fetch_github_issues=true
# Passes existing issues to validate_all()
# Catches BudgetExceededError and exits with code 1
# Writes trace file if trace=true

async def _run_pipeline(
    resolved: Path, config: Config, dry_run: bool, model: str | None, mcp_mgr: MCPManager, *, refresh: bool = False
) -> None
# Core pipeline with optional --refresh flag to force knowledge rebuild

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

### `core/config.py`
```python
Config.load(repo_path: Path) -> Config          # Load from .sigil/config.yml; returns defaults if missing
Config.to_yaml() -> str                          # Serialize to YAML string (for first-run creation)
Config.with_model(model: str) -> Config          # Return copy with different model
Config.model_for(agent: str) -> str              # Resolve model for specific agent

SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
Boldness = Literal["conservative", "balanced", "bold", "experimental"]
ValidationMode = Literal["single", "parallel"]
```

### `core/instructions.py`
```python
def detect_instructions(repo: Path) -> Instructions
# Scans for known agent config files in priority order
# Returns Instructions object with detected_files, source, content
# Detects: AGENTS.md, CLAUDE.md, .cursorrules, .cursor/rules/*, .github/copilot-instructions.md, codex.md
# AGENTS.md takes highest priority; all others also ingested
# Bounded reads: 4000 chars per file, 8000 total
# Single-source detection: each file checked once
```

### `core/llm.py`
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

def set_budget(max_cost_usd: float) -> None
# Sets run budget cap; raises BudgetExceededError if exceeded

def get_usage() -> TokenUsage
# Returns current run's token usage

def get_usage_snapshot() -> tuple[int, int, float]
# Returns (calls, total_tokens, cost_usd)

def write_trace_file(repo_root: Path) -> Path | None
# Writes .sigil/traces/last-run.json with per-call records and summary
```

### `core/utils.py`
```python
async def arun(
    cmd: str | list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30,
) -> tuple[int, str, str]
# Async subprocess execution
# Returns (returncode, stdout, stderr)
# Sanitizes environment (removes secrets)

def get_head(repo: Path) -> str
# git rev-parse HEAD

def now_utc() -> str
# ISO 8601 UTC timestamp

def read_file(path: Path) -> str
# Safe file read, returns "" if missing/unreadable
```

### `core/agent.py`
```python
class Tool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[[dict], Awaitable[ToolResult | str]],
    )
    def schema(self) -> dict
    async def execute(self, args: dict) -> ToolResult

class Agent:
    def __init__(
        self,
        *,
        label: str,
        model: str,
        tools: list[Tool],
        system_prompt: str,
        temperature: float = 0.0,
        max_rounds: int = 10,
        max_tokens: int | None = None,
        agent_key: str = "",
        use_cache: bool = True,
        enable_doom_loop: bool = True,
        enable_masking: bool = True,
        enable_compaction: bool = True,
        on_truncation: TruncationHandler | None = None,
        mcp_mgr: MCPManager | None = None,
        extra_tool_schemas: list[dict] | None = None,
    )
    async def run(
        self,
        *,
        context: dict[str, Any] | None = None,
        messages: list[dict] | None = None,
        on_status: StatusCallback | None = None,
    ) -> AgentResult

@dataclass
class ToolResult:
    content: str
    stop: bool = False
    result: Any = None

@dataclass
class AgentResult:
    messages: list[dict]
    doom_loop: bool
    rounds: int
    stop_result: Any | None
    last_content: str
```

### `pipeline/discovery.py`
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

### `pipeline/knowledge.py`
```python
async def compact_knowledge(repo: Path, model: str, discovery_context: str, *, force_full: bool = False) -> str
# Writes knowledge files to .sigil/memory/, generates INDEX.md
# INIT mode: single LLM call → JSON with all files + index
# INCREMENTAL mode: git diff → read affected files → single LLM call → JSON with changed files + index
# Skips entirely (returns "") if HEAD matches INDEX.md (no new commits) unless force_full=True
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

def rebuild_index(repo: Path) -> str
# Rebuilds INDEX.md from existing knowledge files using H1+H2 headers

def clear_knowledge_cache(repo: Path) -> None
# Clears any in-memory knowledge cache
```

### `state/memory.py`
```python
def load_working(repo: Path) -> str
# Returns working.md content or ""

async def update_working(repo: Path, model: str, run_context: str) -> str
# LLM compacts run context into working.md, returns new content
# Writes YAML frontmatter with last_updated timestamp
```

### `pipeline/maintenance.py`
```python
async def analyze(repo: Path, config: Config) -> list[Finding]
# Returns up to 50 findings, sorted by priority
# Uses read_file tool (max 10 reads) to verify findings
# Reads working memory to avoid re-surfacing addressed findings
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization
```

### `pipeline/ideation.py`
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

### `pipeline/validation.py`
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
# Reviewers MUST provide implementation_spec for approved/adjusted items
```

### `pipeline/executor.py`
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
# Truncation circuit breaker: breaks after 3 consecutive output truncations

async def execute_parallel(
    repo: Path, config: Config, items: list[WorkItem]
) -> list[tuple[WorkItem, ExecutionResult, str]]
# Parallel worktree execution
# Returns (item, result, branch) tuples; branch="" if worktree creation failed
# Cleans up failed worktrees immediately

async def _generate_summary_from_diff(
    diff: str, task_description: str, existing_summary: str | None, model: str
) -> str
# Generates PR summary from git diff using LLM
# Falls back to existing_summary if generation fails
```

### `integrations/github.py`
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

async def generate_pr_summary(
    diff: str, item: WorkItem, executor_summary: str, model: str
) -> str
# Generates LLM-written PR summary from diff and task context
# Falls back to executor_summary or diff stats if generation fails

async def open_pr(
    client: GitHubClient,
    item: WorkItem,
    result: ExecutionResult,
    branch: str,
    repo: Path,
    instructions: Instructions | None = None,
    *,
    summary_model: str = "",
) -> str | None
# Push branch + create PR, returns PR URL or None
# If summary_model provided, generates LLM summary from diff

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
    *,
    instructions: Instructions | None = None,
) -> tuple[list[str], list[str], set[str]]
# Returns (pr_urls, issue_urls, pushed_branches)
# Enforces max_prs_per_run and max_issues_per_run limits
# Uses selector model for PR summary generation

async def cleanup_after_push(
    repo: Path,
    results: list[tuple[WorkItem, ExecutionResult, str]],
    pushed_branches: set[str] | None = None,
) -> None
# Removes worktrees + local branches for pushed branches
```

### `core/mcp.py`
```python
class MCPManager:
    def add_server(self, name: str, session: ClientSession, tools: list[Any], purpose: str = "") -> None
    def get_tools(self) -> list[dict]
    def has_tool(self, name: str) -> bool
    async def call_tool(self, name: str, arguments: dict) -> str
    def should_defer(self, model: str) -> bool
    def get_tool_summaries(self) -> list[dict]
    def search_tools(self, query: str) -> list[dict]

def prepare_mcp_for_agent(mcp_mgr: MCPManager, model: str) -> tuple[list[dict], list[dict], str]
# Returns (extra_builtins, initial_mcp_tools, prompt_section)
# Decides whether to defer tool loading based on count and context window

def handle_search_tools_call(mcp_mgr: MCPManager, args: dict, mcp_tool_schemas: list[dict]) -> str
# Handles search_tools calls, returns matching tool schemas

def format_mcp_tools_for_prompt(tools: list[dict], server_purposes: dict[str, str] | None = None) -> str
# Generates prompt text for MCP tools

def format_deferred_mcp_tools_for_prompt(summaries: list[dict], server_purposes: dict[str, str] | None = None) -> str
# Generates prompt text for deferred MCP tools (name + description only)
```

## LLM Tool Schemas

### Knowledge Tools
- **`load_knowledge_files`** — `{filenames: list[str]}` — used in `select_knowledge`
- **`read_knowledge_file`** — `{filename: str}` — used in incremental `compact_knowledge` (LLM reads existing files before updating)

### Analysis Tools
- **`read_file`** (maintenance) — `{file: str}` — verify findings against source
- **`report_finding`** — `{category, file, line?, description, risk, suggested_fix, disposition, priority, rationale}` — used in `analyze`
- **`report_idea`** — `{title, description, rationale, complexity, disposition, priority}` — used in `ideate`

### Validation Tool
- **`review_item`** — `{index: int, action: "approve"|"adjust"|"veto", new_disposition?: str, reason: str, spec: str}` — used in `validate_all`
  - `index` is zero-based across combined list (findings first, then ideas)
  - `spec` is REQUIRED when action is "approve" or "adjust" with disposition "pr"
  - `spec` contains concrete implementation plan for executor agent

### Executor Tools
- **`read_file`** — `{file: str, offset?: int, limit?: int}` — read file content (capped at 2000 lines / 50KB)
- **`apply_edit`** — `{file, old_content, new_content}` — surgical find-and-replace (exact match required, must be unique)
- **`create_file`** — `{file, content}` — create new file (fails if exists)
- **`done`** — `{summary: str}` — signal completion, exits tool loop
  - Summary MUST be at least 200 characters
  - Must cover: problem solved, files changed, functions added, tests added, integration, key decisions

## Constants

```python
# pipeline/executor.py
DEFAULT_MAX_TOOL_CALLS = 50         # Max tool calls per executor pass (configurable)
COMMAND_TIMEOUT = 120               # seconds for pre/post hook commands
OUTPUT_TRUNCATE_CHARS = 4000        # error output truncated before sending to LLM
MAX_READ_LINES = 2000               # max lines returned by read_file
MAX_READ_BYTES = 50_000             # max bytes returned by read_file
MIN_SUMMARY_LENGTH = 200            # minimum characters for done summary
AGENT_OUTPUT_CAPS = {"analyzer": 16384, "ideator": 8192, "validator": 8192, "reviewer": 8192, "arbiter": 8192, "codegen": 32768}
WORKTREE_DIR = ".sigil/worktrees"

# pipeline/knowledge.py
MAX_KNOWLEDGE_FILES = 150
RESERVED_FILES = frozenset({"INDEX.md", "working.md"})
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 2000
MAX_DIFF_CHARS_PER_FILE = 10_000
MAX_TOTAL_DIFF_CHARS = 100_000
MAX_INCREMENTAL_ROUNDS = 3
MAX_CONCURRENT_DIFFS = 20
MAX_TOOL_READ_CHARS = 100_000

# pipeline/maintenance.py
MAX_FILE_READS = 10                 # max read_file calls per analysis run
MAX_FILE_CHARS = 8000               # truncation for read_file responses

# pipeline/discovery.py
MAX_FILE_LIST = 500
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000

# integrations/github.py
SIGIL_LABEL = "sigil"
SIGIL_LABEL_COLOR = "7B68EE"
SIMILARITY_THRESHOLD = 0.6          # Jaccard similarity for fuzzy dedup

# pipeline/ideation.py
IDEAS_DIR = "ideas"
TEMP_RANGES = {
    "balanced": (0.1, 0.5),
    "bold": (0.2, 0.7),
    "experimental": (0.3, 0.9),
}

# core/llm.py
MAX_RETRIES = 3
INITIAL_DELAY = 1.0
BACKOFF_FACTOR = 2.0
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10
DOOM_LOOP_THRESHOLD = 3

# core/instructions.py
INSTRUCTION_SOURCES = [
    ("AGENTS.md", "AGENTS.md (universal)", False),
    ("CLAUDE.md", "Claude Code", False),
    (".cursor/rules", "Cursor", True),
    (".cursorrules", "Cursor (legacy)", False),
    (".github/copilot-instructions.md", "GitHub Copilot", False),
    ("codex.md", "Codex (OpenAI)", False),
]
PER_FILE_MAX_CHARS = 4000
MAX_TOTAL_CHARS = 8000

# core/mcp.py
MCP_CONNECT_TIMEOUT = 60
MCP_CALL_TIMEOUT = 30
MCP_RESULT_MAX_CHARS = 8000
DEFERRED_MIN_TOOLS = 10
DEFERRED_CONTEXT_RATIO = 0.10
```

## Known Notes

- `ExecutionResult.failure_type` is a typed semantic category for structured failure analysis (see 063).
- `implementation_spec` field on `Finding` and `FeatureIdea` is populated by validation agent and consumed by executor.
- `max_tool_calls` in Config defaults to 50, replacing the hardcoded `MAX_TOOL_CALLS_PER_PASS = 15`.
- `Instructions` renamed from `AgentConfig` (ticket 076).
- Code reorganized into subpackages: `core/`, `pipeline/`, `state/`, `integrations/` (ticket 076).
