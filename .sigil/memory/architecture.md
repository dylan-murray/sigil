# Architecture — Sigil

## High-Level Pipeline

Sigil runs as a single async process. Entry point is `sigil run`, which calls `asyncio.run(_run(...))`.

```
sigil run
    │
    ├── Config load / auto-init (.sigil/config.yml)
    │
    ├── GitHub client setup (GITHUB_TOKEN → PyGithub)
    │
    ├── Knowledge staleness check (git HEAD vs INDEX.md)
    │   ├── [stale] Discovery → compact_knowledge
    │   └── [fresh] Skip discovery
    │
    ├── Analysis + Ideation (asyncio.gather — parallel)
    │   ├── analyze() → list[Finding]
    │   └── ideate() → list[FeatureIdea]
    │
    ├── Validation (asyncio.gather — parallel)
    │   ├── validate(findings) → list[Finding]
    │   └── validate_ideas(ideas) → list[FeatureIdea]
    │
    ├── Deduplication (check GitHub for existing PRs/issues)
    │
    ├── execute_parallel() → list[(WorkItem, ExecutionResult, branch)]
    │   └── asyncio.Semaphore(max_parallel_agents) limits concurrency
    │       Each item: create worktree → execute → commit → rebase
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
- Orchestrates the full pipeline
- Rich terminal UI (panels, status spinners, result display)
- Auto-creates `.sigil/config.yml` on first run
- `_format_run_context()` builds summary for working memory

### `config.py`
- `Config` dataclass (frozen, slots) with all settings
- `Config.load(repo_path)` — strict YAML validation, unknown fields raise
- `Config.to_yaml()` — serializes defaults for first-run creation
- `Boldness` literal type: `"conservative" | "balanced" | "bold" | "experimental"`
- Default model: `anthropic/claude-sonnet-4-6`

### `discovery.py`
- `discover(repo, model) -> str` — returns raw discovery context string
- Reads: directory structure, README, CLAUDE.md, package manifest, git log, source files
- Detects language via marker files (pyproject.toml → python, etc.)
- Detects CI via directory/file presence
- Budget system: `_source_budget(model)` scales with context window
- `_summarize_source_files()` — reads raw file content (budget-truncated), skips binary/skip-dirs/already-read files
- Parallel: `git ls-files` + `git log` run via `asyncio.gather`

### `knowledge.py`
- `compact_knowledge(repo, model, discovery_context)` — LLM writes knowledge files via `write_knowledge_file` tool
- `select_knowledge(repo, model, task_description)` — LLM picks relevant files via `load_knowledge_files` tool
- `is_knowledge_stale(repo)` — compares git HEAD to `<!-- head: {sha} -->` in INDEX.md
- `_generate_index()` — LLM generates INDEX.md with thorough per-file descriptions
- Knowledge budget: `context_window / 4`, capped at 200k chars
- Skips writing `INDEX.md` and `working.md` (managed separately)

### `memory.py`
- `load_working(repo) -> str` — reads `.sigil/memory/working.md`
- `update_working(repo, model, run_context)` — LLM compacts run context into working.md
- YAML frontmatter with `last_updated` timestamp
- Keeps working.md under 100 lines (LLM compacts old history)

### `maintenance.py`
- `analyze(repo, config) -> list[Finding]` — LLM reports findings via `report_finding` tool
- Boldness controls analysis scope (conservative → only clear-cut, experimental → wide net)
- Findings include: category, file, line, description, risk, suggested_fix, disposition, priority, rationale
- Capped at 50 findings, sorted by priority
- Reads working memory to avoid re-surfacing addressed findings

### `ideation.py`
- `ideate(repo, config) -> list[FeatureIdea]` — dual-temperature LLM passes
  - Pass 1: low temperature (focused, obvious improvements)
  - Pass 2: high temperature (creative, novel ideas)
- `conservative` boldness → returns empty list immediately
- `validate_ideas(repo, config, ideas)` — LLM reviews each idea (approve/adjust/veto)
- `save_ideas(repo, ideas)` — writes to `.sigil/ideas/*.md` with YAML frontmatter
- TTL-based cleanup: ideas older than `idea_ttl_days` are deleted
- `_load_existing_ideas()` — prevents re-proposing already-filed ideas

### `validation.py`
- `validate(repo, config, findings) -> list[Finding]` — LLM reviews each finding
- Actions: approve (keep as-is), adjust (change disposition), veto (remove)
- Unreviewed findings default to `disposition="issue"` (conservative fallback)
- Uses `validate_finding` tool with `finding_index` for precise targeting

### `executor.py`
- `execute(repo, config, item) -> ExecutionResult` — single-item execution
  - LLM uses `read_file`, `apply_edit`, `create_file`, `done` tools
  - Lint → test → retry loop (up to `max_retries`)
  - Rollback on failure via `git checkout` + file deletion
- `execute_parallel(repo, config, items)` — parallel worktree execution
  - `asyncio.Semaphore(max_parallel_agents)` for concurrency control
  - Each item: `_create_worktree()` → `execute()` → `_commit_changes()` → `_rebase_onto_main()`
  - Failed items: `downgraded=True`, `downgrade_context` set
- Worktrees at `.sigil/worktrees/<slug>/`
- Branch naming: `sigil/auto/<slug>-<unix_timestamp>`
- Memory snapshot copied to worktree at creation time
- Rebase: memory conflicts auto-resolved (take main's version), code conflicts → downgrade

### `github.py`
- `create_client(repo)` — detects remote URL, creates PyGithub client
- `dedup_items(client, items)` — checks open PRs, open issues, closed issues for title matches
- `open_pr(client, item, result, branch, repo)` — push branch + create PR
- `open_issue(client, item, downgrade_context)` — create issue with structured body
- `publish_results()` — orchestrates PR + issue creation with limits
- `cleanup_after_push()` — removes worktrees + local branches after push
- Rate limiting: tenacity retry on 403/429 with exponential backoff
- Label auto-creation: `sigil` label + `sigil:{category}` category labels

### `llm.py`
- `get_context_window(model) -> int` — returns model's input token limit
- `get_max_output_tokens(model) -> int` — returns model's output token limit
- `MODEL_OVERRIDES` dict for models where litellm info is wrong/missing
- Falls back to 32k context / 8192 output if model info unavailable

### `utils.py`
- `arun(cmd, *, cwd, timeout) -> (rc, stdout, stderr)` — async subprocess
  - String cmd → `create_subprocess_shell`
  - List cmd → `create_subprocess_exec`
  - Handles timeout (kills process), FileNotFoundError
- `get_head(repo) -> str` — git rev-parse HEAD
- `now_utc() -> str` — ISO 8601 UTC timestamp
- `read_file(path) -> str` — safe file read, returns "" if missing

## Async Model

- **LLM calls:** `litellm.acompletion` (non-blocking)
- **Subprocess:** `asyncio.create_subprocess_exec/shell` via `arun()`
- **GitHub API:** PyGithub is sync — wrapped with `asyncio.to_thread()`
- **Parallelism:** `asyncio.gather()` for independent operations, `asyncio.Semaphore` for bounded concurrency
- **No threading:** Except `to_thread` for PyGithub sync calls

## Data Flow

```
discover() → raw context string
    ↓
compact_knowledge() → .sigil/memory/*.md files
    ↓
select_knowledge() → dict[filename, content]  (per-agent)
    ↓
analyze() / ideate() → list[Finding] / list[FeatureIdea]
    ↓
validate() / validate_ideas() → filtered + triaged lists
    ↓
dedup_items() → DedupResult (skipped + remaining)
    ↓
execute_parallel() → list[(WorkItem, ExecutionResult, branch)]
    ↓
publish_results() → PR URLs + issue URLs
    ↓
update_working() → .sigil/memory/working.md
```

## Key Design Principles

- **Conservative by default:** One bad PR kills trust permanently
- **CI must pass:** Never open a PR with failing lint or tests
- **Small, focused PRs:** One concern per PR, easy to review
- **Transparent reasoning:** Every PR explains what and why
- **Persistent memory:** Learn from previous runs, don't repeat mistakes
- **Tool-use pattern:** Structured LLM output via tool calls, no raw JSON parsing
