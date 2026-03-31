# Sigil API Reference — Core Data Structures and Tool Schemas

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
    relevant_files: tuple[str, ...] = () # Files for executor to preload
    boldness: str = "balanced" # Boldness level at which this finding was generated
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
    relevant_files: tuple[str, ...] = () # Files for executor to preload
    boldness: str = "balanced" # Boldness level at which this idea was generated
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
    failure_type: str | None = None  # Typed semantic failure category
    doom_loop_detected: bool = False # Whether a doom loop was detected
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
    ignore: list[str] = []              # Glob patterns to ignore
    max_prs_per_run: int = 3
    max_github_issues: int = 5
    max_ideas_per_run: int = 15
    idea_ttl_days: int = 180
    pre_hooks: list[str] = []           # Commands to run before code generation (failure aborts)
    post_hooks: list[str] = []          # Commands to run after code generation (failure triggers retry)
    max_retries: int = 2
    max_parallel_tasks: int = 3
    agents: dict[str, dict] = {}        # Per-agent model and iteration overrides
    directive_phrase: str = "@sigil work on this"  # Phrase to scan for in issue comments
    arbiter: bool = False               # Enable parallel validation with challenger + arbiter
    max_spend_usd: float = 20.0          # Run budget cap
    mcp_servers: list[dict] = []        # External MCP tool servers
    sandbox: SandboxMode = "none"       # "none"|"nemoclaw"|"docker"
    sandbox_allowlist: tuple[str, ...] = () # Domains allowed in sandbox network
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
    task: str | None = None
    content: str | None = None
```

### FileTracker (internal, pipeline/models.py)
```python
@dataclass
class FileTracker:
    modified: set[str]   # Files modified via apply_edit
    created: set[str]    # Files created via create_file
    last_read: dict[str, float] # Timestamp of last read for staleness check
    read_keys: dict[str, int] # Counts reads per file:offset for doom loop
    read_totals: dict[str, int] # Counts total reads per file for hard stop
```

## Public Functions by Module

### `cli.py`
```python
def init(repo: Path) -> None
# Initializes a Sigil project in the target repository by creating .sigil/config.yml

async def _run(repo: Path, dry_run: bool, trace: bool, *, refresh: bool = False) -> None
# Main async pipeline
# Uses config.model_for("compactor") for compact_knowledge()
# Fetches existing issues if GitHub client is connected
# Passes existing issues to validate_all()
# Catches BudgetExceededError and exits with code 1
# Writes trace file if trace=true

async def _run_pipeline(
    resolved: Path, config: Config, dry_run: bool, mcp_mgr: MCPManager, *, refresh: bool = False, trace: bool = False
) -> None
# Core pipeline with optional --refresh flag to force knowledge rebuild
```

### `core/config.py`
```python
Config.load(repo_path: Path) -> Config          # Load from .sigil/config.yml; returns defaults if missing
Config.to_yaml() -> str                          # Serialize to YAML string (for first-run creation)
Config.with_model(model: str) -> Config          # Return copy with different model
Config.model_for(agent: str) -> str              # Resolve model for specific agent
Config.max_iterations_for(agent: str) -> int     # Resolve max iterations for specific agent
Config.max_tokens_for(agent: str) -> int | None  # Resolve max tokens for specific agent
Config.is_ignored(path: str) -> bool             # Checks if a path is ignored by config

SIGIL_DIR = ".sigil"
CONFIG_FILE = "config.yml"
MEMORY_DIR = "memory"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
Boldness = Literal["conservative", "balanced", "bold", "experimental"]
SandboxMode = Literal["none", "nemoclaw", "docker"]
```

### `core/instructions.py`
```python
def detect_instructions(repo: Path) -> Instructions
# Scans for known agent config files in priority order
# Returns Instructions object with detected_files, source, content
# Detects: AGENTS.md, CLAUDE.md, .cursor/rules/*, .cursorrules, .github/copilot-instructions.md, codex.md
# AGENTS.md takes highest priority; all others also ingested
# Bounded reads: 4000 chars per file, 8000 total
# Single-source detection: each file checked once
```

### `core/llm.py`
```python
async def acompletion(*, label: str = "unknown", **kwargs: Any) -> litellm.ModelResponse
# Async LLM call with exponential backoff retry
# Retries APIError, InternalServerError, RateLimitError, ServiceUnavailableError, Timeout, asyncio.TimeoutError
# MAX_RETRIES=3, INITIAL_DELAY=1.0s, BACKOFF_FACTOR=2.0
# Records per-call trace with label, model, tokens, cost
# Checks budget after each call; raises BudgetExceededError if exceeded

def get_context_window(model: str) -> int
# Returns model's max input tokens (MODEL_OVERRIDES → litellm → fallback 32k)

def get_max_output_tokens(model: str) -> int
# Returns model's max output tokens (MODEL_OVERRIDES → litellm → fallback 8192)

def detect_doom_loop(messages: list[dict]) -> tuple[str, str] | None
# Returns (tool_name, tool_args) if last 5 tool calls are identical (same name + args) within a 10-message window

def mask_old_tool_outputs(messages: list[dict], *, keep_recent: int = 6) -> list[dict]
# Replaces tool result content older than keep_recent with placeholders
# Modifies messages in-place; idempotent

async def compact_messages(messages: list[dict], model: str, *, threshold_tokens: int | None = None, keep_recent: int = 5, last_prompt_tokens: int | None = None) -> bool
# LLM summarizes old context when estimated tokens exceed threshold
# Modifies messages in-place; only triggers once per call

def supports_prompt_caching(model: str) -> bool
# Returns True if model supports prompt caching

def cacheable_message(model: str, prompt: str) -> dict
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

def read_truncated(path: Path, max_chars: int = 8000) -> str
# Reads file content up to max_chars, appends truncation marker

def fix_double_escaped(text: str) -> str
# Fixes common double-escaped strings from LLM output

def numbered_window(lines: list[str], center: int, radius: int = 10) -> str
# Returns a numbered window of lines around a center line

def find_all_match_locations(content: str, old_content: str) -> list[int]
# Finds all line numbers where old_content matches

def format_ambiguous_matches(content: str, old_content: str, file: str) -> str
# Formats an error message for ambiguous matches in apply_edit

def find_best_match_region(content: str, old_content: str) -> str
# Finds a region in content similar to old_content for error messages

def fuzzy_find_match(content: str, old_content: str) -> tuple[str, float, int] | None
# Performs a fuzzy match for old_content in content
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
        mutating: bool = False,
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
        use_cache: bool = True,
        enable_doom_loop: bool = True,
        enable_masking: bool = True,
        enable_compaction: bool = True,
        on_truncation: TruncationHandler | None = None,
        mcp_mgr: MCPManager | None = None,
        extra_tool_schemas: list[dict] | None = None,
        tool_model: str | None = None,
        escalate_after: int = 10,
        subagents: dict[str, SubAgent] | None = None,
        forced_final_tool: str | None = None,
    )
    async def run(
        self,
        *,
        context: dict[str, Any] | None = None,
        messages: list[dict] | None = None,
        on_status: StatusCallback | None = None,
    ) -> AgentResult

class AgentCoordinator:
    def add_agent(self, name: str, agent: Agent, initial_messages: list[dict]) -> None
    def inject(self, name: str, message: dict) -> None
    async def run_agent(self, name: str, *, on_status: StatusCallback | None = None) -> AgentResult
    def get_history(self, name: str) -> list[dict]

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
async def discover(repo: Path, model: str, *, ignore: list[str] | None = None, on_status: StatusCallback | None = None) -> DiscoveryData
# Returns DiscoveryData object containing:
# - Name, language, CI, top-level dirs, file count
# - File listing (git ls-files, max 500)
# - README, CLAUDE.md content
# - Package manifest content
# - Recent commits (last 15)
# - Source file contents (budget-truncated, raw)
```

### `pipeline/knowledge.py`
```python
async def compact_knowledge(repo: Path, model: str, discovery: DiscoveryData | str, *, force_full: bool = False, compactor_max_tokens: int | None = None, discovery_max_tokens: int | None = None, on_status: StatusCallback | None = None) -> str
# Writes knowledge files to .sigil/memory/, generates INDEX.md
# INIT mode: single LLM call → JSON with all files + index
# INCREMENTAL mode: git diff → read affected files → single LLM call → JSON with changed files + index
# Skips entirely (returns "") if manifest matches (no new commits) unless force_full=True
# Returns path to INDEX.md, or "" if nothing written

async def select_memory(repo: Path, model: str, task_description: str, *, max_tokens: int | None = None) -> dict[str, str]
# Returns {filename: content} for relevant knowledge files
# LLM reads INDEX.md and calls load_memory_files tool

async def is_knowledge_stale(repo: Path) -> bool
# True if INDEX.md missing or git manifest hash doesn't match stored manifest hash

def load_index(repo: Path) -> str
# Returns INDEX.md content or ""

def load_knowledge_file(repo: Path, filename: str) -> str
# Returns single knowledge file content or ""

def load_memory_files(repo: Path, filenames: list[str]) -> dict[str, str]
# Returns {filename: content} for requested files

def rebuild_index(repo: Path) -> str
# Rebuilds INDEX.md from existing knowledge files using H1+H2 headers

def clear_memory_cache() -> None
# Clears any in-memory knowledge cache
```

### `state/memory.py`
```python
def load_working(repo: Path) -> str
# Returns working.md content or ""

async def update_working(repo: Path, model: str, run_context: str, *, manifest_hash: str | None = None, max_tokens: int | None = None) -> str
# LLM compacts run context into working.md, returns new content
# Writes YAML frontmatter with last_updated timestamp and manifest_hash

async def compute_manifest_hash(repo: Path) -> str
# Computes a hash of all tracked files in the repo, excluding .sigil/memory/

def load_manifest_hash(repo: Path) -> str
# Loads the manifest hash from working.md frontmatter
```

### `pipeline/maintenance.py`
```python
async def analyze(repo: Path, config: Config, *, instructions: Instructions | None = None, mcp_mgr: MCPManager | None = None, on_status: StatusCallback | None = None) -> list[Finding]
# Returns up to 50 findings, sorted by priority
# Uses read_file tool to verify findings
# Reads working memory to avoid re-surfacing addressed findings
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization
```

### `pipeline/ideation.py`
```python
async def ideate(repo: Path, config: Config, *, instructions: Instructions | None = None, on_status: StatusCallback | None = None) -> list[FeatureIdea]
# Returns deduplicated ideas from two temperature passes
# Returns [] if boldness == "conservative"
# Does NOT save to disk — caller must call save_ideas()
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization

def save_ideas(repo: Path, ideas: list[FeatureIdea]) -> list[Path]
# Writes ideas to .sigil/ideas/*.md with YAML frontmatter
# Returns list of written file paths

def load_open_ideas(repo: Path, ttl_days: int = 180) -> list[FeatureIdea]
# Loads open ideas from .sigil/ideas/, pruning stale ones

def mark_idea_done(repo: Path, title: str) -> None
# Marks an idea as done in its YAML frontmatter
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
    instructions: Instructions | None = None,
    mcp_mgr: MCPManager | None = None,
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
    repo: Path, config: Config, item: WorkItem,
    *, source_repo: Path | None = None, instructions: Instructions | None = None, mcp_mgr: MCPManager | None = None, on_status: StatusCallback | None = None
) -> tuple[ExecutionResult, FileTracker]
# Single-item execution on given repo path (no worktree management)
# LLM uses read_file/apply_edit/create_file/done tools
# read_file supports offset and limit params; capped at 2000 lines / 50KB
# Pre-hooks run before code generation; failure aborts
# Post-hooks run after code generation; failure triggers retry
# Uses prompt caching if model supports it
# Uses mask_old_tool_outputs() and compact_messages() for cost optimization
# Truncation circuit breaker: breaks after 3 consecutive output truncations

async def execute_parallel(
    repo: Path, config: Config, items: list[WorkItem],
    *, run_id: str = "", instructions: Instructions | None = None, mcp_mgr: MCPManager | None = None, on_status: StatusCallback | None = None, on_item_status: ItemStatusCallback | None = None, on_item_done: ItemDoneCallback | None = None
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
) -> tuple[str, str]
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
# Uses engineer model for PR summary generation

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

async def connect_mcp_servers(config: Config) -> AsyncIterator[MCPManager]
# Context manager to connect to MCP servers defined in config

def prepare_mcp_for_agent(mcp_mgr: MCPManager | None, model: str) -> tuple[list[dict], list[dict], str]
# Returns (extra_builtins, initial_mcp_tools, prompt_section)
# Decides whether to defer tool loading based on count and context window

def handle_search_tools_call(mcp_mgr: MCPManager, args: dict, active_tools: list[dict]) -> str
# Handles search_tools calls, returns matching tool schemas

def format_mcp_tools_for_prompt(tools: list[dict], server_purposes: dict[str, str] | None = None) -> str
# Generates prompt text for MCP tools

def format_deferred_mcp_tools_for_prompt(summaries: list[dict], server_purposes: dict[str, str] | None = None) -> str
# Generates prompt text for deferred MCP tools (name + description only)
```

## LLM Tool Schemas

### Knowledge Tools
- **`load_memory_files`** — `{filenames: list[str]}` — used in `select_memory`
- **`read_knowledge_file`** — `{filename: str}` — used in incremental `compact_knowledge` (LLM reads existing files before updating)

### Analysis Tools
- **`read_file`** (maintenance) — `{file: str, offset?: int, limit?: int}` — verify findings against source
- **`report_finding`** — `{category, file, line?, description, risk, suggested_fix, disposition, priority, rationale}` — used in `analyze`
- **`report_idea`** — `{title, description, rationale, complexity, disposition, priority}` — used in `ideate`

### Validation Tool
- **`review_item`** — `{index: int, action: "approve"|"adjust"|"veto", new_disposition?: str, reason: str, spec?: str, relevant_files?: list[str], priority?: int}` — used in `validate_all`
  - `index` is zero-based across combined list (findings first, then ideas)
  - `spec` is REQUIRED when action is "approve" or "adjust" with disposition "pr"
  - `spec` contains concrete implementation plan for executor agent
  - `relevant_files` is REQUIRED when action is "approve" or "adjust" with disposition "pr"
  - `priority` is REQUIRED when action is "approve" or "adjust"
- **`veto_duplicates`** — `{duplicate_pairs: list[list[int]]}` — used in `validate_all` to remove duplicate items in bulk
- **`resolve_item`** — `{index: int, action: "approve"|"adjust"|"veto", new_disposition?: str, reason: str}` — used by the arbiter agent to resolve disagreements

### Executor Tools
- **`read_file`** — `{file: str, offset?: int, limit?: int}` — read file content (capped at 2000 lines / 50KB)
- **`apply_edit`** — `{file, old_content, new_content}` — surgical find-and-replace (exact match required, must be unique)
- **`multi_edit`** — `{file, edits: list[{old_content, new_content}]}` — apply multiple sequential edits to a single file
- **`create_file`** — `{file, content}` — create new file (fails if exists)
- **`grep`** — `{pattern: str, path?: str, include?: str}` — search file contents using regex
- **`list_directory`** — `{path?: str, depth?: int}` — list files and subdirectories
- **`task_progress`** — `{summary: str}` — signal completion, exits tool loop
  - Summary MUST be at least 200 characters
  - Must cover: problem solved, files changed, functions added, tests added, integration, key decisions
- **`verify_hook`** — `{}` — re-run failed post-hooks to verify fixes

## Constants

```python
# pipeline/executor.py
COMMAND_TIMEOUT = 120               # seconds for pre/post hook commands
OUTPUT_TRUNCATE_CHARS = 12000       # error output truncated before sending to LLM
MIN_SUMMARY_LENGTH = 200            # minimum characters for task_progress summary
MAX_PRELOAD_FILES = 15              # Max files to preload into executor context
MAX_PRELOAD_BYTES = 100_000         # Max bytes of preloaded files
DIFF_PER_FILE_CAP = 4000            # Max chars for diff of a single file in PR summary
DIFF_TOTAL_CAP = 15000              # Max total chars for diff in PR summary
MAX_REVIEWER_TOOL_CALLS = 20        # Max tool calls for reviewer agent
WORKTREE_DIR = ".sigil/worktrees"

# pipeline/knowledge.py
MAX_KNOWLEDGE_FILES = 150
RESERVED_FILES = frozenset({"INDEX.md", "working.md"})
CHARS_PER_TOKEN = 3                 # Estimated chars per token for budget calculations
PROMPT_OVERHEAD_TOKENS = 2000
MAX_DIFF_CHARS_PER_FILE = 10_000
MAX_TOTAL_DIFF_CHARS = 100_000
MAX_INCREMENTAL_ROUNDS = 3
MAX_CONCURRENT_DIFFS = 20
MAX_TOOL_READ_CHARS = 100_000

# pipeline/maintenance.py
MAX_LLM_ROUNDS = 10                 # Max rounds for maintenance agent
MAX_READS_HARD_STOP = 10            # Max read_file calls per file before hard stop

# pipeline/discovery.py
MAX_FILE_LIST = 500
PROMPT_OVERHEAD_TOKENS = 8_000
RESPONSE_RESERVE_TOKENS = 4_000

# integrations/github.py
SIGIL_LABEL = "sigil"
SIGIL_LABEL_COLOR = "7B68EE"
SIMILARITY_THRESHOLD = 0.6

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
DOOM_LOOP_WINDOW = 10               # Number of recent messages to check for doom loop
DOOM_LOOP_MAX_REPEATS = 5           # Number of identical tool calls to trigger doom loop
DEFAULT_COMPACTION_THRESHOLD = 80_000 # Token threshold for message compaction
COMPACTION_RATIO = 0.4              # Ratio of context window to use as compaction threshold
TOOL_RESULT_MAX_CHARS = 10_000      # Max chars for tool result in trace

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

# state/chronic.py
CHRONIC_INJECT_THRESHOLD = 1        # Failures before injecting context
CHRONIC_DOWNGRADE_THRESHOLD = 2     # Failures before downgrading to issue
CHRONIC_SKIP_THRESHOLD = 3          # Failures before skipping entirely

# state/attempts.py
MAX_ATTEMPTS = 500                  # Max attempt records to keep in attempts.jsonl
```
