# Configuration — Sigil

## Configuration File Location

**`.sigil/config.yml`** — Committed to the repository, auto-created on first `sigil run`.

## Configuration Schema

```yaml
version: 1                           # Config schema version (stripped before validation)
model: anthropic/claude-sonnet-4-6   # LLM model to use (litellm format)
fast_model: null                     # Optional faster model for knowledge compaction (preferred over knowledge_model)
knowledge_model: null                # Optional separate model for knowledge compaction (deprecated, use fast_model)
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
fetch_github_issues: true            # Whether to fetch existing issues
max_github_issues: 25                # Max issues to fetch
directive_phrase: "@sigil work on this"  # Phrase to scan for in issue comments
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

## `fast_model` Field

Optional faster model for knowledge compaction (preferred over `knowledge_model`):

```yaml
fast_model: anthropic/claude-haiku-4-5-20251001  # Use faster model for compaction
model: anthropic/claude-sonnet-4-6                # Use stronger model for analysis/execution
```

When set, `compact_knowledge()` uses `fast_model` instead of `model`. Useful for reducing cost since compaction is a structured summarization task that doesn't require the strongest model.

## `knowledge_model` Field (Deprecated)

Optional separate model for knowledge compaction (use `fast_model` instead):

```yaml
knowledge_model: openai/gpt-4o-mini   # Use cheaper model for compaction
model: anthropic/claude-sonnet-4-6    # Use stronger model for analysis/execution
```

When set, `compact_knowledge()` uses `knowledge_model` instead of `model`. Preference order: `fast_model` > `knowledge_model` > `model`.

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

Maintainers add this phrase as a comment on any GitHub issue they want Sigil to prioritize. The validator receives these issues with a `has_directive` flag and boosts their priority. Example:

```
@sigil work on this
```

The phrase is case-insensitive and must appear anywhere in the comment body.

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
fast_model: anthropic/claude-haiku-4-5-20251001
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
fetch_github_issues: true
max_github_issues: 50
directive_phrase: "@sigil work on this"
```

## Known Gap

The `ignore` field in `config.yml` is documented but **currently unused in filtering logic**. Files matching ignore patterns are not actually excluded from discovery or analysis. This is a known gap — see the `.sigilignore` idea in `.sigil/ideas/` for a proposed fix.
