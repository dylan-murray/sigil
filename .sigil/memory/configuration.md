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
lint_cmd: null                       # Custom lint command (null = auto-detect)
test_cmd: null                       # Custom test command (null = auto-detect)
max_retries: 3                       # Max retries for failed executions
max_parallel_agents: 3               # Max parallel worktrees
```

**Strict validation:** Unknown fields raise `ValueError`. `boldness` must be a valid enum value. `schedule` field was removed — scheduling is external.

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

## Environment Variables

Required at runtime:

```bash
# LLM API key (choose one based on model)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# GitHub integration (required in live mode — fails fast if missing)
GITHUB_TOKEN=ghp_...
```

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

## CLI Commands

```bash
sigil run                          # Analyze repo, open PRs/issues (auto-inits on first run)
sigil run --dry-run                # Analyze only, don't open PRs or issues
sigil run --model openai/gpt-4o   # Override model from config
sigil run --repo /path/to/repo    # Specify repo path (default: current directory)
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
lint_cmd: uv run ruff check .
test_cmd: uv run pytest tests/ -x -q
max_retries: 3
max_parallel_agents: 3
```

## Known Gap

The `ignore` field in `config.yml` is documented but **currently unused in filtering logic**. Files matching ignore patterns are not actually excluded from discovery or analysis. This is a known gap — see the `.sigilignore` idea in `.sigil/ideas/` for a proposed fix.
