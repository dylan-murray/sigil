<!-- head: 8a8ec4b | updated: 2026-03-25T03:37:29Z -->

# Architecture — Sigil Pipeline, Agent Framework, and Subpackage Structure

## High-Level Pipeline

Sigil runs as a single async process. Entry point is `sigil run`, which calls `asyncio.run(_run(...))`. The pipeline respects existing agent config files in target repos (AGENTS.md, CLAUDE.md, .cursorrules, etc.) and injects them into all agent prompts. It also fetches existing GitHub issues and uses them in validation to avoid duplicating work.

```
sigil run
    │
    ├── Config load / auto-init (.sigil/config.yml)
    │
    ├── GitHub client setup (GITHUB_TOKEN → PyGithub)
    │   └── Fails fast if no GITHUB_TOKEN in live mode
    │
    ├── Fetch existing GitHub issues (if fetch_github_issues=true)
    │   ├── Open issues with 'sigil' label
    │   ├── Scan comments for '@sigil work on this' directive
    │   └── Pass to validation as context
    │
    ├── Agent config detection (AGENTS.md, CLAUDE.md, .cursorrules, etc.)
    │   └── Inject into all agent prompts (AGENTS.md takes priority)
    │
    ├── Knowledge staleness check (git HEAD vs INDEX.md HTML comment)
    │   ├── [stale] discover() → compact_knowledge()
    │   └── [fresh] Skip discovery entirely
    │
    ├── MCP connect (async: connect configured MCP servers,
    │   discover tools — graceful on failure)
    │
    ├── Analysis + Ideation (asyncio.gather — parallel)
    │   ├── analyze() → list[Finding]
    │   └── ideate() → list[FeatureIdea]
    │
    ├── Validation (async: validate findings + review ideas)
    │   ├── single mode (default): one triager LLM pass
    │   └── parallel mode: two challengers + arbiter for disagreements
    │
    ├── Deduplication (check GitHub for existing PRs/issues)
    │   └── dedup_items() → DedupResult
    │
    ├── PR cap enforcement (overflow → issue queue)
    │
    ├── execute_parallel() → list[(WorkItem, ExecutionResult, branch)]
    │   └── asyncio.Semaphore(max_parallel_agents) limits concurrency
    │       Each item: create worktree → engineer builds → QA writes tests
    │       → commit → rebase
    │
    ├── publish_results() → PR URLs + issue URLs
    │   ├── open_pr() for successful executions
    │   └── open_issue() for failures + issue-disposition items
    │
    ├── cleanup_after_push() — remove worktrees + local branches
    │
    └── update_working() — compact run context into working.md
```

## Component Responsibilities

### `cli.py`
- Top-level `run` command with `asyncio.run()` at entry
- Orchestrates the full pipeline in `_run()`
- Rich terminal UI (panels, status spinners, result display)
- Auto-creates `.sigil/config.yml` on first run (lazy-init)
- `_format_run_context()` builds summary string for working memory update
- Fails fast with clear error if `GITHUB_TOKEN` missing in live mode
- CLI flags: `--repo` (default `.`), `--dry-run`, `--model`, `--trace`
- Uses `config.model_for("compactor")` when calling `compact_knowledge()`
- Fetches existing issues early in pipeline if `config.fetch_github_issues=true`
- Passes existing issues to `validate_all()` for deduplication
- Catches `BudgetExceededError` and exits with code 1
- Writes trace file if `--trace` flag set
- **Imports from subpackages:** `sigil.core.instructions`, `sigil.state.attempts`, `sigil.state.chronic`, `sigil.core.config`, `sigil.pipeline.discovery`, `sigil.pipeline.executor`, `sigil.integrations.github`, `sigil.pipeline.ideation`, `sigil.pipeline.knowledge`, `sigil.core.llm`, `sigil.pipeline.maintenance`, `sigil.core.mcp`, `sigil.state.memory`, `sigil.core.utils`, `sigil.pipeline.validation`

### `core/config.py`
- `Config` dataclass (frozen, slots) with all settings
- `Config.load(repo_path)` — strict YAML validation; unknown fields raise `ValueError`
- `Config.to_yaml()` — serializes defaults for first-run creation
- `Config.with_model(model)` — returns copy with different model
- `Boldness` literal type: `"conservative" | "balanced" | "bold" | "experimental"`
- Default model: `anthropic/claude-sonnet-4-6`
- `version` field stripped before validation; `schedule` field removed (scheduling is external)
- `fast_model` field removed — replaced by per-agent model config
- `agents: dict[str, dict]` — per-agent model overrides (agent-specific → global `model` fallback)
- `model_for(agent: str) -> str` — resolves model for a given agent name; cheap models (Haiku) auto-default for ideator/compactor/memory/selector
- `validation_mode: str` — `"single"` (default) or `"parallel"` (two challengers + arbiter)
- `fetch_github_issues: bool = True` — whether to fetch existing issues
- `max_github_issues: int = 25` — max issues to fetch
- `directive_phrase: str = "@sigil work on this"` — phrase to scan for in issue comments
- `max_cost_usd: float = 20.0` — run budget cap; raises `BudgetExceededError` if exceeded

### `core/instructions.py`
- `detect_instructions(repo) -> Instructions` — scans for known agent config files
- Detects: AGENTS.md, CLAUDE.md, .cursorrules, .cursor/rules/*, .github/copilot-instructions.md, codex.md
- AGENTS.md takes highest priority; all others are also ingested
- Returns `Instructions` dataclass with `detected_files`, `source`, `content`
- `has_instructions` property checks if content exists
- `format_for_prompt()` and `format_for_pr_body()` for different contexts
- Bounded reads: respects file size limits (4000 chars per file, 8000 total), skips binary files
- Single-source detection: each file checked once
- **Renamed from:** `agent_config.py` / `detect_agent_config()` / `AgentConfig`

### `core/llm.py`
- `acompletion(label, **kwargs)` — async wrapper around `litellm.acompletion` with exponential backoff retry
  - Retries on `InternalServerError`, `RateLimitError`, `ServiceUnavailableError`
  - `MAX_RETRIES = 3`, `INITIAL_DELAY = 1.0`, `BACKOFF_FACTOR = 2.0`
  - Records per-call trace with label, model, tokens, cost
  - Checks budget after each call; raises `BudgetExceededError` if exceeded
- `get_context_window(model) -> int` — returns model's input token limit
- `get_max_output_tokens(model) -> int` — returns model's output token limit
- `get_agent_output_cap(agent, model) -> int` — returns per-agent output token cap
- `detect_doom_loop(messages) -> bool` — detects 3 identical consecutive tool calls
- `mask_old_tool_outputs(messages, keep_recent=10)` — replaces old tool results with placeholders
- `compact_messages(messages, model, threshold_tokens=80000)` — LLM summarizes old context when threshold exceeded
- `supports_prompt_caching(model) -> bool` — checks if model supports prompt caching
- `cacheable_message(model, content) -> dict` — builds message with cache control if supported
- `compute_call_cost(model, prompt_tok, completion_tok, cache_read_tok, cache_creation_tok) -> float` — calculates cost including cache multipliers
- `TokenUsage` dataclass tracks prompt/completion/cache tokens and cost
- `CallTrace` dataclass records per-call trace: timestamp, label, model, tokens, cost
- `write_trace_file(repo_root) -> Path | None` — writes `.sigil/traces/last-run.json` with per-call records and summary
- `set_budget(max_cost_usd)` — sets run budget cap
- `MODEL_OVERRIDES` dict for models where litellm info is wrong/missing
- Falls back to 32k context / 8192 output if model info unavailable
- `litellm.suppress_debug_info = True` set at module level

### `core/mcp.py`
- Async MCP client — connects to external tool servers configured in `.sigil/config.yml`
- Tools namespaced as `mcp__<server>__<tool>` (matching Claude Code, Agent SDK, Codex convention)
- Tracks per-server `purpose` field for category-level hints in agent prompts
- **Key types:**
  - `MCPManager` — holds sessions, per-server locks, tool map, and server purposes
  - `format_mcp_tools_for_prompt()` — generates prompt text; groups by server with purpose descriptions when available, falls back to flat list otherwise
  - `format_deferred_mcp_tools_for_prompt()` — generates prompt text when tools are deferred (name + description only, instructs agent to use `search_tools`)
  - `mcp_tool_to_litellm()` — converts MCP tool schema to litellm-compatible dict
  - `_namespaced()` — produces `mcp__server__tool` from server + tool names
  - `estimate_tool_tokens()` — estimates token cost of tool schemas (chars / 4)
  - `SEARCH_TOOLS_TOOL` — built-in tool definition for runtime tool discovery
  - `prepare_mcp_for_agent()` — entry point for agents; decides defer vs. full load
  - `handle_search_tools_call()` — handles `search_tools` calls, injects schemas into the active tool list at runtime
- **Deferred tool loading:** When there are ≥10 MCP tools and their schemas would exceed 10% of the model's context window, tools are deferred. Agents receive only names and descriptions plus a `search_tools` built-in. Constants: `DEFERRED_MIN_TOOLS=10`, `DEFERRED_CONTEXT_RATIO=0.10`.
- **Agent integration:** All agents call `prepare_mcp_for_agent(mcp_mgr, model)` → `(extra_builtins, initial_mcp_tools, prompt_section)`. Agents add `extra_builtins` to their tool list, include `initial_mcp_tools` (full schemas when not deferred), and append `prompt_section` to the system prompt. During the agent loop, `search_tools` calls are handled via `handle_search_tools_call()`.
- **Connection flow:** config → `_validate_server_cfg()` → `_connect_one()` (interpolates env vars, connects stdio/SSE) → `manager.add_server(name, session, tools, purpose)` → tools available to all agents.
- **Transports:** stdio (spawns local process) and SSE (connects to remote URL)
- **Graceful degradation:** Failed MCP connections warn and continue; pipeline is not aborted

### `core/utils.py`
- `arun(cmd, *, cwd, timeout) -> (rc, stdout, stderr)` — async subprocess
  - String cmd → `create_subprocess_shell`; list cmd → `create_subprocess_exec`
  - Handles timeout (kills process), FileNotFoundError gracefully
  - Sanitizes environment variables (removes secrets, keeps allowlisted vars)
- `get_head(repo) -> str` — git rev-parse HEAD
- `now_utc() -> str` — ISO 8601 UTC timestamp
- `read_file(path) -> str` — safe file read, returns "" if missing/unreadable

### `core/agent.py`
- **Agent framework (ticket 073)** — unified abstraction for all 5 agent loops
- `Tool` class — name, description, parameters, handler co-located; `schema()` renders OpenAI-format tool schema
- `Agent` class — config + loop in one object; `run(context=...)` executes the agent
- `ToolResult` dataclass — `content` (text to LLM), `stop` (exit loop), `result` (structured data)
- `AgentResult` dataclass — `messages`, `doom_loop`, `rounds`, `stop_result`, `last_content`
- **Design principles:**
  1. Agent is a class — config + loop in one object. No separate "runner."
  2. Tool is a class — name, description, parameters, handler co-located.
  3. Context flows via `run(context=...)` — handoffs are just `agent.run(context={...})`.
  4. Programmatic handoffs — pipeline decides the next agent, not the LLM.
  5. Zero behavior change — migration produces identical LLM calls and tool dispatch.
- **Tool dispatch:** O(1) lookup via `_tool_map: dict[str, Tool]`; MCP tools via `_handle_mcp_tools()`
- **Context injection:** `string.Template.safe_substitute` for `$context` placeholders in prompts
- **Features:** doom loop detection, message masking, compaction, truncation handling, MCP integration, output caps
- All 5 agents (maintenance, ideation, validation, executor, knowledge) migrated to use this framework

### `pipeline/discovery.py`
- `discover(repo, model) -> str` — returns raw discovery context string
- Reads: directory structure, README, CLAUDE.md, package manifest, git log, source files
- Detects language via marker files (`pyproject.toml` → python, etc.)
- Detects CI via directory/file presence (`.github/workflows/`, `.circleci/`, etc.)
- Budget system: `_source_budget(model)` scales with model context window
- `_summarize_source_files()` — reads raw file content (budget-truncated), skips binary/skip-dirs/already-read files
- Parallel: `git ls-files` + `git log` run via `asyncio.gather`

### `pipeline/knowledge.py`
- `compact_knowledge(repo, model, discovery_context)` — two modes:
  - **INIT**: single LLM call → JSON with all files + index (no tool loop for writing)
  - **INCREMENTAL**: git diff since last HEAD → `read_knowledge_file` tool reads → single LLM call → JSON with only changed files + updated index
  - Skips entirely if HEAD matches INDEX.md (zero LLM calls)
- `select_knowledge(repo, model, task_description)` — LLM picks relevant files via `load_knowledge_files` tool
- `is_knowledge_stale(repo)` — compares git HEAD to `<!-- head: {sha} -->` in INDEX.md
- INDEX.md generated in the same LLM call as knowledge files (no separate call)
- Knowledge budget: `context_window / 4`, capped at 200k chars
- Cannot write `INDEX.md` or `working.md` (reserved; silently skipped)
- Uses `Agent` framework for incremental compaction (ticket 073)

### `pipeline/maintenance.py`
- `analyze(repo, config) -> list[Finding]` — LLM reports findings via `report_finding` tool
- Also has `read_file` tool for verifying findings against actual source (max 10 reads)
- Boldness controls analysis scope (conservative → only clear-cut, experimental → wide net)
- Findings include: category, file, line, description, risk, suggested_fix, disposition, priority, rationale
- Capped at 50 findings, sorted by priority
- Reads working memory to avoid re-surfacing addressed findings
- Injects agent config context into analysis prompt
- Uses `Agent` framework (ticket 073) — tools defined as `Tool` objects, loop in `Agent.run()`

### `pipeline/ideation.py`
- `ideate(repo, config) -> list[FeatureIdea]` — dual-temperature LLM passes
  - Pass 1: low temperature (focused, obvious improvements)
  - Pass 2: high temperature (creative, novel ideas)
- `conservative` boldness → returns empty list immediately
- `save_ideas(repo, ideas)` — writes to `.sigil/ideas/*.md` with YAML frontmatter
- TTL-based cleanup: ideas older than `idea_ttl_days` are deleted on load
- `_load_existing_ideas()` — prevents re-proposing already-filed ideas
- `_deduplicate()` — case-insensitive slug dedup across both passes
- Injects agent config context into ideation prompt
- No MCP tools — ideator is minimal (only `report_idea` tool)
- Uses `Agent` framework (ticket 073) — tools defined as `Tool` objects, loop in `Agent.run()`

### `pipeline/validation.py`
- `validate_all(repo, config, findings, ideas, existing_issues) -> ValidationResult` — unified validation
- **Single mode** (default): one triager LLM pass reviews all candidates together
- **Parallel mode** (`validation_mode: parallel`): two independent challenger agents run concurrently via `asyncio.gather`, then an arbiter agent resolves disagreements per item
- Receives existing GitHub issues as context to avoid duplicating work
- Uses `review_item` tool with `index` field (findings first, then ideas with offset)
- Actions: approve (keep as-is), adjust (change disposition), veto (remove)
- Unreviewed findings default to `disposition="issue"` (conservative fallback)
- Unreviewed ideas kept as-is
- Checks `[FILE EXISTS]` / `[FILE MISSING]` tags to catch hallucinated file paths
- Logs vetoed items at INFO level
- Existing issues with `@sigil work on this` directive are marked for priority boost
- Each triager/challenger/arbiter can use a different model via `agents.triager` / `agents.challenger` / `agents.arbiter` config
- Uses `Agent` framework (ticket 073) — tools defined as `Tool` objects, loop in `Agent.run()`

### `pipeline/executor.py`
- `execute(repo, config, item) -> (ExecutionResult, _ChangeTracker)` — single-item execution
  - LLM uses `read_file`, `apply_edit`, `create_file`, `done` tools
  - `read_file` supports `offset` and `limit` params; capped at 2000 lines / 50KB
  - Pre-hooks run before code generation; failure aborts
  - Post-hooks run after code generation; failure triggers retry
  - Rollback on failure via `git checkout` + file deletion
- `execute_parallel(repo, config, items)` — parallel worktree execution
  - `asyncio.Semaphore(max_parallel_agents)` for concurrency control
  - Each item: `_create_worktree()` → `execute()` → `_commit_changes()` → `_rebase_onto_main()`
  - Failed items: `downgraded=True`, `downgrade_context` set
- Worktrees at `.sigil/worktrees/<slug>/`
- Branch naming: `sigil/auto/<slug>-<unix_timestamp>`
- Memory snapshot copied to worktree at creation time
- Rebase: memory conflicts auto-resolved (take main's version), code conflicts → downgrade
- Injects agent config context into execution prompt
- Uses prompt caching for large context (if model supports it)
- Uses `Agent` framework (ticket 073) — tools defined as `Tool` objects, loop in `Agent.run()`
- **Write protection:** `.sigil/` directory is write-protected; executor cannot modify memory/config files
- **Execution flow:** Engineer agent builds the feature → QA agent writes tests and reviews code → post-hooks (lint/test) run → if hooks fail, QA gets error output and fixes it → post-hooks run again → loop until pass or max retries

### `state/memory.py`
- `load_working(repo) -> str` — reads `.sigil/memory/working.md`
- `update_working(repo, model, run_context)` — LLM compacts run context into working.md
- YAML frontmatter with `last_updated` timestamp
- Keeps working.md under 100 lines (LLM compacts old history)

### `state/attempts.py`
- `AttemptRecord` dataclass — tracks execution attempts per work item
- `read_attempts(repo) -> list[AttemptRecord]` — load attempt history
- `log_attempt(repo, item, result)` — record new attempt
- `format_attempt_history(repo, item) -> str` — format for LLM context
- `prune_attempts(repo, max_keep=10)` — remove old attempts

### `state/chronic.py`
- `WorkItem` type alias — `Union[Finding, FeatureIdea]`
- `Finding` dataclass — maintenance finding with category, file, line, description, etc.
- `FeatureIdea` dataclass — feature proposal with title, description, rationale, etc.
- `fingerprint(item) -> str` — unique identifier for deduplication
- `slugify(text) -> str` — URL-safe slug generation

### `integrations/github.py`
- `create_client(repo)` — detects remote URL, creates PyGithub client; returns `None` if no token
- `fetch_existing_issues(client, max_issues, directive_phrase)` — fetches open issues with 'sigil' label
  - Scans issue comments for directive phrase (case-insensitive)
  - Returns `list[ExistingIssue]` with `has_directive` flag
  - Truncates issue body to 200 chars
- `dedup_items(client, items)` — checks open PRs, open issues, closed issues for title matches
  - Uses exact match, category+file key match, AND token-similarity (Jaccard ≥ 0.6)
- `open_pr(client, item, result, branch, repo)` — push branch + create PR
- `open_issue(client, item, downgrade_context)` — create issue with structured body
- `publish_results()` — orchestrates PR + issue creation with limits
- `cleanup_after_after_push()` — removes worktrees + local branches after push
- Rate limiting: tenacity retry on 403/429 with exponential backoff
- Label auto-creation: `sigil` label + `sigil:{category}` category labels

## Agents

| Agent        | Role                                                              |
|--------------|-------------------------------------------------------------------|
| `auditor`    | Scans the codebase for bugs, dead code, security issues, and style violations |
| `ideator`    | Proposes new features and improvements based on codebase analysis  |
| `triager`    | Reviews findings and ideas — decides what's worth acting on       |
| `challenger` | Second opinion on triager decisions (parallel validation mode)    |
| `arbiter`    | Breaks ties when triager and challenger disagree                  |
| `selector`   | Picks which knowledge files are relevant for a given task         |
| `engineer`   | Implements code changes — builds features, writes production code |
| `qa`         | Writes tests, reviews engineer's code, fixes bugs found by post-hooks |
| `discovery`  | Reads repo structure and git history (pipeline stage, not agentic)|
| `compactor`  | Compresses discovery output into persistent knowledge files       |
| `memory`     | Updates working memory after a run                                |

**Default model:** All agents use the global `model` setting (intended to be lightweight). Users override specific agents via `agents:` in config.yml — typically `engineer` and `qa` get a stronger coding model.

**Execution flow:** Engineer runs once to build the feature → QA writes tests and reviews the code → post-hooks (lint/test) run → if hooks fail, QA gets the error output and fixes it → post-hooks run again → loop until pass or max retries.

**Agent framework:** `Agent` class in `core/agent.py` handles the LLM loop (tool calls, doom loop detection, message compaction). `AgentCoordinator` manages multiple agents with persistent conversation histories for multi-agent flows.

## Async Model

- **LLM calls:** `litellm.acompletion` via `llm.acompletion()` wrapper (non-blocking, with retry)
- **Subprocess:** `asyncio.create_subprocess_exec/shell` via `arun()`
- **GitHub API:** PyGithub is sync — wrapped with `asyncio.to_thread()`
- **Parallelism:** `asyncio.gather()` for independent operations, `asyncio.Semaphore` for bounded concurrency
- **No threading:** Except `to_thread` for PyGithub sync calls

Sync PyGitHub HTTP calls are wrapped with `asyncio.to_thread`.

## Data Flow

```
discover() → raw context string
    ↓
detect_instructions() → Instructions object
    ↓
compact_knowledge() → .sigil/memory/*.md files
    ↓
mcp_connect() → MCPManager (tools available to all agents)
    ↓
select_knowledge() → dict[filename, content]  (per-agent)
    ↓
fetch_existing_issues() → list[ExistingIssue]
    ↓
analyze() / ideate() → list[Finding] / list[FeatureIdea]
    ↓
validate_all(existing_issues) → ValidationResult (filtered + triaged)
    ↓
dedup_items() → DedupResult (skipped + remaining)
    ↓
execute_parallel() → list[(WorkItem, ExecutionResult, branch)]
    ↓
publish_results() → PR URLs + issue URLs
    ↓
update_working() → .sigil/memory/working.md
```

## Module Table

| Module                    | Role                                                         |
|---------------------------|--------------------------------------------------------------|
| `cli.py`                  | Async: orchestrates full pipeline, Rich UI, budget enforcement |
| `core/config.py`          | Sync: loads `.sigil/config.yml`, validates, resolves models  |
| `core/instructions.py`    | Sync: detects repo agent config files (AGENTS.md, etc.)      |
| `core/llm.py`             | Async: acompletion wrapper with retry; token tracking; cost computation; doom loop detection; message masking/compaction |
| `core/mcp.py`             | Async: MCP client — connects to external tool servers, namespaces tools as `mcp__server__tool`, tracks per-server purpose for category hints |
| `core/utils.py`           | Async: arun() subprocess helper, get_head(), read_file()     |
| `core/agent.py`           | **Agent framework (ticket 073)** — Tool, Agent, ToolResult, AgentResult classes; unified loop abstraction for all 5 agents |
| `pipeline/discovery.py`   | Async: reads repo structure + source files                   |
| `pipeline/knowledge.py`   | Async: compacts discovery → knowledge files via acompletion; uses Agent framework |
| `pipeline/maintenance.py` | Async: auditor agent finds problems via acompletion + tool_use |
| `pipeline/validation.py`  | Async: triager/challenger/arbiter validate findings; single or parallel mode |
| `pipeline/ideation.py`    | Async: ideator proposes improvements via acompletion + tool_use |
| `pipeline/executor.py`    | Async: engineer builds features, QA writes tests + fixes, parallel worktrees |
| `state/memory.py`         | Async: manages working.md via acompletion                    |
| `state/attempts.py`       | Sync: tracks execution attempts per work item                |
| `state/chronic.py`        | Sync: WorkItem types (Finding, FeatureIdea), fingerprinting  |
| `integrations/github.py`  | Async: push (arun), PyGitHub calls (to_thread)               |

## Key Design Principles

- **Conservative by default:** One bad PR kills trust permanently
- **CI must pass:** Never open a PR with failing lint or tests
- **Small, focused PRs:** One concern per PR, easy to review
- **Transparent reasoning:** Every PR explains what and why
- **Persistent memory:** Learn from previous runs, don't repeat mistakes
- **Tool-use pattern:** Structured LLM output via tool calls, no raw JSON parsing
- **Agent framework (ticket 073):** All 5 agents use unified `Agent` + `Tool` abstraction; zero behavior change from migration
- **Single-call compaction:** Knowledge compaction uses one LLM call (INIT) or one call + tool reads (INCREMENTAL) — not a multi-round write loop
- **Fail fast:** Missing GITHUB_TOKEN in live mode → immediate error, not silent degradation
- **Respects agent configs:** Detects AGENTS.md, .cursorrules, copilot-instructions, etc. and injects into all agent prompts
- **Avoids duplicate work:** Fetches existing GitHub issues and uses them in validation to prevent re-proposing tracked work
- **Model-agnostic:** Uses litellm; tested against OpenAI, Anthropic, Gemini, Bedrock, Azure, Mistral
- **Copy industry patterns:** Tool naming, deferred loading, and MCP conventions follow Claude Code / Agent SDK / Codex
- **Cost optimization:** Observation masking, tool output truncation, per-agent model defaults, conditional tool loading, client-side compaction, doom loop detection, run budget cap
- **Write protection:** `.sigil/` directory is write-protected; agents cannot modify memory/config files
- **Modular architecture:** Code organized into `core/`, `pipeline/`, `state/`, `integrations/` subpackages for clarity and maintainability
- **Subpackage reorganization (ticket 076):** 17 modules moved from flat `sigil/` into 4 subpackages by responsibility: `core/` (foundational), `pipeline/` (5-stage pipeline), `integrations/` (external systems), `state/` (persistence + history)
