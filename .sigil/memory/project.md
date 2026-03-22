# Project Overview — Sigil

## What is Sigil?

Sigil is an LLM-agnostic autonomous repository improvement agent that proactively finds improvements and ships pull requests while you sleep. It runs on a schedule (via GitHub Actions or any scheduler), analyzes the codebase, and opens small, safe PRs for low-risk improvements. High-risk findings become GitHub issues. Bring any model — OpenAI, Anthropic, Gemini, or any of 100+ providers supported by litellm.

**The gap it fills:** Every existing tool is either reactive (triggered by humans) or narrow-scoped (only dependencies, only reviews). Sigil is proactive and general-purpose.

## Target Users

- Development teams who want automated code maintenance
- Open source maintainers who need help with routine improvements
- Organizations seeking proactive code quality improvements without manual effort

## Language & Stack

- **Language:** Python 3.11+
- **Package Manager:** uv
- **CLI Framework:** typer + rich for terminal UI
- **LLM Integration:** litellm (model-agnostic — Anthropic, OpenAI, Gemini, etc.)
- **GitHub Integration:** PyGithub for PR/issue management
- **Async Runtime:** Full async/await with asyncio throughout
- **Configuration:** YAML-based `.sigil/config.yml`
- **Retry Logic:** tenacity for GitHub API rate limiting

## How to Build / Test / Lint

```bash
# Install dependencies
uv sync

# Run the CLI
uv run sigil --help
uv run sigil run --repo .
uv run sigil run --repo . --dry-run
uv run sigil run --repo . --model openai/gpt-4o

# Run tests
uv run pytest
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v

# Lint and format (ALWAYS run last after code changes)
uv run ruff format .
uv run ruff check .
```

## Project Structure

```
sigil/
├── __init__.py          # Version: 0.1.0
├── __main__.py          # Entry point
├── cli.py               # CLI commands + main pipeline orchestration
├── config.py            # Config loading/validation
├── discovery.py         # Repo structure reading + source file budget
├── knowledge.py         # Knowledge compaction + selection
├── memory.py            # Working memory management
├── maintenance.py       # Maintenance analysis agent
├── ideation.py          # Feature ideation agent
├── validation.py        # Finding/idea validation agent (unified)
├── executor.py          # Code generation + worktree execution
├── github.py            # GitHub PR/issue integration
├── agent_config.py      # Agent config file detection (AGENTS.md, .cursorrules, etc.)
├── llm.py               # LLM model info helpers + retry wrapper
└── utils.py             # Async subprocess (arun), git helpers, timestamps

tests/
├── conftest.py          # Shared fixtures (currently empty)
├── unit/                # Fast unit tests — all external services mocked
│   ├── test_config.py
│   ├── test_discovery.py
│   ├── test_executor.py
│   ├── test_github.py
│   ├── test_ideation.py
│   ├── test_knowledge.py
│   ├── test_llm.py
│   ├── test_maintenance.py
│   ├── test_utils.py
│   ├── test_validation.py
│   └── test_agent_config.py
└── integration/         # Integration tests (real services — currently empty)

examples/
└── github-action.yml    # GitHub Action workflow template

.sigil/                  # Runtime directory (created on first run)
├── config.yml           # User configuration
├── memory/              # Persistent knowledge base
│   ├── INDEX.md         # Knowledge index (HEAD SHA + per-file descriptions)
│   ├── working.md       # Operational history (managed by memory.py)
│   └── *.md             # Topic knowledge files
└── ideas/               # Feature idea storage
    └── *.md             # Individual idea files with YAML frontmatter
```

## Business Model & Phases

**Phase 1 — The Tool (current focus):**
- Open source CLI + GitHub Action
- User brings their own LLM API key
- Runs on schedule, opens PRs/issues
- Goal: 500 repos on the free tool

**Phase 2 — The Platform (future):**
- Hosted SaaS version (no API key needed)
- Cross-repo learning + fine-tuned models
- Dashboard, run history, trends
- Connectors: Linear, Slack, Jira, PagerDuty
- Teams + orgs + SSO

## Current Status

Phase 1 MVP pipeline is complete. 108+ tests passing. Full async pipeline, no tree-sitter dependency. Dogfooding complete (issue #010 done — 2 runs on sigil itself, 8 PRs, 25 issues). Knowledge compaction rewritten for single-call JSON (issue #028 done). Agent config detection implemented (issue #029 done).

Open Phase 1 issues: #030 (live progress output), #031 (validate against GitHub issues).
Phase 2 backlog: #011–015, #025–027, #033.

## Key Constraints / Hard Rules

- **NEVER commit without running `/commit-review` first** (project rule)
- **NEVER write tests directly** — use `/test-writer` skill
- **Run `uv run ruff format .` as the LAST step** after ALL code changes
- No comments in code unless logic is genuinely non-obvious
- Phase 1 only: CLI + GitHub Action, no platform features yet
- Every PR opened must have CI passing before merge is suggested
- Conservative by default — when in doubt, open an issue not a PR
- No CI configured in this repo yet (none detected)
- Respect existing agent config files in target repos (AGENTS.md, CLAUDE.md, .cursorrules, etc.)

## Issue Tracker

Issues live in `.issues/` (gitignored from public repo). Closed issues in `.closed_issues/`. The `/pm` skill manages issue lifecycle.

## Known Bugs (from working memory)

- `execute_parallel` uses `""` as sentinel for "no branch" — should be `str | None`
- `apply_edit` has no guard against empty `old_content` (potential full-file replacement)
- `MODEL_OVERRIDES` in `llm.py` may be dead code (no tests verify it's used)
- `DEFAULT_MODEL` in `config.py` (`anthropic/claude-sonnet-4-6`) doesn't match `configuration.md`
- Integration test directory is empty — no tests for GitHub API, LLM calls, or git worktree ops
- Package not yet published to PyPI (GitHub Action example uses `uv tool install sigil`)
