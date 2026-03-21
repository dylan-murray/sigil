# Configuration — Sigil

## Configuration File Location

**`.sigil/config.yml`** — Committed to the repository, auto-created on first run.

## Configuration Schema

```yaml
version: 1                           # Config schema version
model: anthropic/claude-sonnet-4-20250514  # LLM model to use
boldness: bold                       # Analysis aggressiveness level
focus:                               # Areas to focus analysis on
  - tests
  - dead_code
  - security
  - docs
  - types
  - features
ignore:                              # Patterns to ignore
  - "vendor/**"
  - "*.generated.*"
max_prs_per_run: 3                   # Limit PRs opened per run
max_issues_per_run: 5                # Limit issues opened per run
max_ideas_per_run: 15                # Limit ideas generated per run
idea_ttl_days: 180                   # Days before ideas expire
lint_cmd: null                       # Custom lint command (null = auto-detect)
test_cmd: null                       # Custom test command (null = auto-detect)
max_retries: 3                       # Max retries for failed executions
max_parallel_agents: 3               # Max parallel worktrees
```

## Boldness Levels

Controls how aggressively Sigil analyzes and proposes changes:

### conservative
- **Maintenance:** Only clear-cut problems (unused imports, obvious bugs)
- **Features:** No feature ideation (maintenance only)
- **Risk tolerance:** Very low, only near-certain improvements

### balanced (default)
- **Maintenance:** Confident issues and well-justified improvements
- **Features:** Obvious gaps, low-risk additions (missing error handling, CLI flags)
- **Risk tolerance:** Medium, avoid speculative findings

### bold
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

## Environment Variables

Required at runtime:

```bash
# LLM API key (choose one based on model)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# GitHub integration
GITHUB_TOKEN=ghp_...
```

Optional overrides:

```bash
# Override config boldness
SIGIL_CONSERVATISM=conservative
```

## Model Configuration

Sigil uses **litellm** for model-agnostic LLM access. Supported formats:

### Anthropic
```yaml
model: anthropic/claude-sonnet-4-20250514
model: anthropic/claude-haiku-4-20250514
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

### Others
Any model supported by litellm works. See [litellm providers](https://docs.litellm.ai/docs/providers).

## Auto-Detection

### Lint Command
If `lint_cmd` is null, Sigil detects based on project:
- Python: `uv run ruff format .` or `ruff format .`
- JavaScript/TypeScript: `npm run lint` or `yarn lint`
- Other: No linting

### Test Command
If `test_cmd` is null, Sigil detects based on project:
- Python: `uv run pytest` or `pytest`
- JavaScript/TypeScript: `npm test` or `yarn test`
- Other: No testing

## Configuration Validation

### Strict Validation
- Unknown fields raise clear errors
- `boldness` must be valid enum value
- Numeric fields validated for reasonable ranges

### Migration
- `version: 1` is current schema
- Future versions will include migration logic
- Old configs without version default to 1

## Memory Directory

**`.sigil/memory/`** — Persistent knowledge and working memory:

- `INDEX.md` — Knowledge file index with descriptions
- `project.md`, `architecture.md`, etc. — Knowledge files
- `working.md` — Operational history and learnings

## Ideas Directory

**`.sigil/ideas/`** — Feature idea storage:

- Individual `.md` files for each proposed idea
- YAML frontmatter with metadata
- TTL-based cleanup of old ideas

## GitHub Action Configuration

For scheduled runs, use this workflow template:

```yaml
name: Sigil
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM daily
  workflow_dispatch:

jobs:
  sigil:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v4
      - run: uv tool install sigil
      - run: sigil run
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```
