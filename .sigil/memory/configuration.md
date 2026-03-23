# Configuration — Sigil

## Configuration File Location

**`.sigil/config.yml`** — Committed to the repository, auto-created on first `sigil run`.

## Configuration Schema

```yaml
version: 1                           # Config schema version (stripped before validation)
model: anthropic/claude-sonnet-4-6   # LLM model to use (litellm format)

boldness: bold                       # Analysis aggressiveness level
focus:                               # Areas to focus analysis on
  - tests
  - dead_code
  - security
  - docs
  - types
  - features
ignore:                              # Glob patterns to ignore (currently unused in filtering)
  - "vendor/**"
  - "*.generated.*"
max_prs_per_run: 3                   # Limit PRs opened per run
max_issues_per_run: 5                # Limit issues opened per run
max_ideas_per_run: 15                # Limit ideas generated per run
idea_ttl_days: 180                   # Days before ideas expire and are deleted
pre_hooks: []                        # Commands to run before code generation (failure aborts)
post_hooks: []                       # Commands to run after code generation (failure triggers retry)
max_retries: 1                       # Max retries for failed executions
max_parallel_agents: 3               # Max parallel worktrees
max_cost_usd: 20.0                   # Run budget cap (default $20)

validation_mode: single              # single (default) | parallel (two reviewers + arbiter)

agents:                              # Per-agent model overrides (optional)
  codegen:
    model: anthropic/claude-opus-4-6
  compactor:
    model: anthropic/claude-haiku-4-5-20251001
  reviewer:                          # parallel mode: each independent reviewer agent
    model: anthropic/claude-sonnet-4-6
  arbiter:                           # parallel mode: resolves disagreements between reviewers
    model: anthropic/claude-opus-4-6

fetch_github_issues: true            # Whether to fetch existing issues
max_github_issues: 50                # Max issues to fetch
directive_phrase: "@sigil work on this"  # Phrase to scan for in issue comments

mcp_servers:                         # Optional: external MCP tool servers
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    purpose: "local filesystem access for reading project files"
  - name: my-sse-server
    url: "http://localhost:3000/sse"
    headers:
      Authorization: "Bearer ${MY_API_KEY}"
    purpose: "product requirements and design docs"
```

**Strict validation:** Unknown fields raise `ValueError`. `boldness` must be a valid enum value. `schedule` field was removed — scheduling is external. `fast_model` field was removed — use per-agent `agents` config instead.

## Boldness Levels

Controls how aggressively Sigil analyzes and proposes changes:

### conservative
- **Maintenance:** Only clear-cut problems (unused imports, obvious bugs)
- **Features:** No feature ideation — `ideate()` returns `[]` immediately
- **Risk tolerance:** Very low, only near-certain improvements

### balanced
- **Maintenance:** Confident issues and well-justified improvements
- **Features:** Obvious gaps, low-risk additions (missing error handling, CLI flags)
- **Risk tolerance:** Medium, avoid speculative findings

### bold (default)
- **Maintenance:** Wider range including potential improvements, refactoring opportunities
- **Features:** Ambitious but scoped (new commands, integrations, significant behavior)
- **Risk tolerance:** Higher, includes fairly confident findings

### experimental
- **Maintenance:** Anything that could be improved, aggressive refactoring
- **Features:** Moonshots, architectural shifts, cross-cutting ideas
- **Risk tolerance:** Highest, cast wide net

## Focus Areas

Controls what types of issues Sigil looks for:

- **tests** — Missing test coverage, broken tests
- **dead_code** — Unused imports, unreachable functions, unused variables
- **security** — Hardcoded secrets, vulnerable dependencies, injection risks
- **docs** — Outdated documentation, broken links, missing docs
- **types** — Missing type annotations, incorrect types
- **features** — New functionality proposals (only if boldness > conservative)

## Validation Mode

`validation_mode` controls how findings and ideas are reviewed:

- **`single`** (default): One LLM reviewer pass over all candidates. Fast and cheap.
- **`parallel`**: Two independent reviewer agents run concurrently via `asyncio.gather`. A third arbiter agent receives both sets of decisions and resolves disagreements per item. Higher quality, ~3x token cost. Opt-in.

In parallel mode, each reviewer and the arbiter can use different models via `agents.reviewer` and `agents.arbiter` config.

## Per-Agent Model Configuration

Each agent can use a different model via the `agents` section. Agent-specific model overrides fall back to the top-level `model` if not set. Cost-sensitive agents (`ideator`, `compactor`, `memory`, `selector`) automatically default to Haiku — override them only if you want something different.

```yaml
model: anthropic/claude-sonnet-4-6  # default for most agents

agents:
  codegen:
    model: anthropic/claude-opus-4-6          # strongest model for code generation
  compactor:
    model: anthropic/claude-haiku-4-5-20251001  # cheap model for knowledge compaction (auto-default)
  reviewer:
    model: anthropic/claude-sonnet-4-6        # parallel validation reviewers
  arbiter:
    model: anthropic/claude-opus-4-6          # parallel validation arbiter
```

Valid agent names: `analyzer`, `ideator`, `validator`, `codegen`, `discovery`, `compactor`, `memory`, `reviewer`, `arbiter`, `selector`. Unknown agent names raise `ValueError`.

Resolution order: `agents.<name>.model` → top-level `model` → agent-specific default (Haiku for cheap agents).

**`fast_model` is deprecated** — use per-agent `agents` config instead.

## Pre and Post Hooks

`pre_hooks` and `post_hooks` specify commands to run during code execution:

```yaml
pre_hooks:
  - uv run ruff check .              # Run before code generation (failure aborts)
post_hooks:
  - uv run ruff format .             # Run after code generation (failure triggers retry)
  - uv run pytest tests/ -x -q
```

- **`pre_hooks`**: Commands run before LLM code generation. If any hook fails, execution is aborted immediately and the item is downgraded to an issue.
- **`post_hooks`**: Commands run after code generation (e.g., formatting, linting, testing). If any hook fails, the LLM is given the error output and retries (up to `max_retries`). If all retries fail, the item is downgraded to an issue.
- Hooks run in order; any failure short-circuits the list (remaining hooks are not executed).
- Both lists are optional (default: empty lists, no hooks run).

Common examples:

```yaml
pre_hooks:
  - uv run ruff check .              # Python: lint baseline
post_hooks:
  - uv run ruff format .             # Python: format
  - uv run pytest tests/ -x -q       # Python: test
```

```yaml
pre_hooks:
  - npm run lint                     # JavaScript: lint baseline
post_hooks:
  - npm run format                   # JavaScript: format
  - npm test                         # JavaScript: test
```

## Run Budget Cap

`max_cost_usd` sets a hard cap on total run cost (default `$20.00`). If the run exceeds this budget, Sigil raises `BudgetExceededError` and exits with code 1. This prevents runaway costs from infinite loops or unexpectedly expensive operations.

```yaml
max_cost_usd: 20.0   # Default: $20 per run
max_cost_usd: 50.0   # Increase for longer runs
```

## GitHub Action (Reusable)

The repo ships a composite action at `action.yml`. Users add one step:

```yaml
- uses: dylan-murray/sigil@main
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Inputs** (all optional):

| Input               | Default                 | Description                          |
|---------------------|-------------------------|--------------------------------------|
| `anthropic-api-key` | —                       | Sets `ANTHROPIC_API_KEY`             |
| `openai-api-key`    | —                       | Sets `OPENAI_API_KEY`                |
| `model`             | —                       | Passed as `--model` flag             |
| `dry-run`           | `"false"`               | Passed as `--dry-run` flag           |
| `sigil-version`     | git install from `main` | uv package spec                      |

`GITHUB_TOKEN` is automatically set from `github.token`. All other config comes from `.sigil/config.yml` in the repo.

See `examples/github-action.yml` for the reusable action workflow and `examples/github-action-manual.yml` for the manual setup variant.

## Environment Variables

| Variable              | Required | Description                        |
|-----------------------|----------|---------------------------------|
| LLM provider key      | Yes      | e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` — depends on configured model |
| `GITHUB_TOKEN`        | Yes      | GitHub token for opening PRs/issues |

## MCP Credentials in CI

MCP server configs in `.sigil/config.yml` support `${VAR}` interpolation for credentials. In CI, these variables must be available in the environment when `sigil run` executes.

**How it works:**

1. Define your MCP server in `.sigil/config.yml` with `${VAR}` placeholders:
   ```yaml
   mcp_servers:
     - name: slack
       command: npx
       args: ["-y", "@anthropic/mcp-server-slack"]
       env:
         SLACK_BOT_TOKEN: "${SLACK_BOT_TOKEN}"
       purpose: "team communication"
     - name: jira
       url: "https://jira-mcp.example.com/sse"
       headers:
         Authorization: "Bearer ${JIRA_API_KEY}"
       purpose: "issue tracker"
   ```

2. Store the actual secrets in your GitHub repo (Settings > Secrets and variables > Actions).

3. Pass them as `env:` on the action step in your workflow:
   ```yaml
   - uses: dylan-murray/sigil@main
     with:
       anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
     env:
       SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
       JIRA_API_KEY: ${{ secrets.JIRA_API_KEY }}
   ```

Environment variables set on the calling step are automatically available to `sigil run` inside the action. The `${VAR}` placeholders are resolved at runtime by `sigil/mcp.py` when connecting to each server. If a variable is missing, Sigil raises a `ValueError` with the variable name.

**Manual workflow variant:** set the same env vars directly on the step that runs `sigil run`:
```yaml
- name: Run Sigil
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
  run: sigil run
```

## MCP Server Config Fields

| Field       | Required | Type         | Description                                  |
|-------------|----------|--------------|----------------------------------------------|
| `name`      | Yes      | string       | Server identifier, must match `[a-zA-Z][a-zA-Z0-9_-]*`, no double underscores |
| `command`   | One of   | string       | Stdio transport: command to run               |
| `url`       | One of   | string       | SSE transport: HTTP endpoint                  |
| `args`      | No       | list[string] | Arguments for stdio command                   |
| `env`       | No       | dict         | Environment variables for stdio process (supports `${VAR}` interpolation) |
| `headers`   | No       | dict         | HTTP headers for SSE transport (supports `${VAR}` interpolation) |
| `timeout`   | No       | float        | Connection timeout in seconds (default: 60)   |
| `purpose`   | No       | string       | Human-readable description of what this server provides; used to generate category-level hints in agent prompts |

Tools are namespaced as `mcp__<server>__<tool>` to avoid collisions across servers. When `purpose` is set, agent prompts group tools by server with the purpose as a category description. Without `purpose`, tools are listed in a flat format.

## Model Configuration

Sigil uses **litellm** for model-agnostic LLM access. Supported formats:

### Anthropic
```yaml
model: anthropic/claude-sonnet-4-6
model: anthropic/claude-opus-4-6-20250527
model: anthropic/claude-haiku-4-5-20251001
```

### OpenAI
```yaml
model: openai/gpt-4o
model: openai/gpt-4o-mini
```

### Google
```yaml
model: gemini/gemini-pro
model: gemini/gemini-flash
```

Any model supported by litellm works. See [litellm providers](https://docs.litellm.ai/docs/providers).

## GitHub Issue Integration

### `fetch_github_issues`

Boolean flag (default `true`) to fetch existing GitHub issues at pipeline start:

```yaml
fetch_github_issues: true   # Fetch open issues with 'sigil' label
```

When enabled, Sigil fetches open issues labeled with `sigil` and passes them to the validation agent. This prevents duplicate work and allows the validator to recognize already-tracked issues.

### `max_github_issues`

Maximum number of existing issues to fetch (default `25`):

```yaml
max_github_issues: 50   # Fetch up to 50 existing issues
```

Higher values give the validator more context but increase API calls. Recommended: 25–50.

### `directive_phrase`

Phrase to scan for in issue comments to mark issues for priority (default `"@sigil work on this"`):

```yaml
directive_phrase: "@sigil work on this"  # Case-insensitive
```

Maintainers add this phrase as a comment on any GitHub issue they want Sigil to prioritize. The validator receives these issues with a `has_directive` flag and boosts their priority.

## CLI Commands

```bash
sigil run                          # Analyze repo, open PRs/issues (auto-inits on first run)
sigil run --dry-run                # Analyze only, don't open PRs or issues
sigil run --model openai/gpt-4o   # Override model from config
sigil run --repo /path/to/repo    # Specify repo path (default: current directory)
sigil run --trace                  # Write per-call LLM trace to .sigil/traces/last-run.json
sigil --version                   # Print version
```

**Removed commands:** `sigil init` (removed in issue #008 — `run` auto-inits), `sigil watch` (scheduling is external).

## Configuration Validation

### Strict Validation
- Unknown fields raise `ValueError` with field names listed
- `boldness` must be one of: `conservative`, `balanced`, `bold`, `experimental`
- `version` field is stripped before validation (not a dataclass field)
- Non-mapping YAML raises `ValueError`
- Invalid YAML raises `ValueError`
- `fast_model` field raises `ValueError` (deprecated — use `agents` config)
- `max_cost_usd` must be positive

## Memory Directory

**`.sigil/memory/`** — Persistent knowledge and working memory:
- `INDEX.md` — Knowledge file index with HEAD SHA
- `project.md`, `architecture.md`, etc. — Knowledge files
- `working.md` — Operational history and learnings

## Ideas Directory

**`.sigil/ideas/`** — Feature idea storage:
- Individual `.md` files for each proposed idea
- YAML frontmatter with metadata (title, summary, status, complexity, disposition, priority, created)
- TTL-based cleanup of old ideas (default 180 days)

## Traces Directory

**`.sigil/traces/`** — Per-call LLM trace logs (created with `--trace` flag):
- `last-run.json` — Trace file from last run with per-call records and summary by label
- Format: `{started_at, total_cost_usd, total_calls, calls[], summary_by_label{}}`

## Sigil's Own Config (`.sigil/config.yml` in this repo)

```yaml
version: 1
model: anthropic/claude-sonnet-4-6
boldness: experimental
focus: [tests, dead_code, security, docs, types, features]
ignore: []
max_prs_per_run: 5
max_issues_per_run: 5
max_ideas_per_run: 15
idea_ttl_days: 180
pre_hooks:
- uv run ruff check .
post_hooks:
- uv run ruff format .
- uv run pytest tests/ -x -q
max_retries: 1
max_parallel_agents: 3
max_cost_usd: 20.0
fetch_github_issues: true
max_github_issues: 50
directive_phrase: "@sigil work on this"
agents:
  compactor:
    model: anthropic/claude-haiku-4-5-20251001
```

## Known Gap

The `ignore` field in `config.yml` is documented but **currently unused in filtering logic**. Files matching ignore patterns are not actually excluded from discovery or analysis. This is a known gap — see the `.sigilignore` idea in `.sigil/ideas/` for a proposed fix.
