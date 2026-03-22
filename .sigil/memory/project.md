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
- **MCP Client:** `mcp` SDK for connecting to external tool servers

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
uv run pytest tests/integration/ -m integration -v

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
├── config.py            # Config loading/validation, per-agent model resolution
├── discovery.py         # Repo structure reading + source file budget
├── knowledge.py         # Knowledge compaction + selection
├── memory.py            # Working memory management
├── maintenance.py       # Maintenance analysis agent
├── ideation.py          # Feature ideation agent
├── validation.py        # Finding/idea validation (single or parallel mode)
├── executor.py          # Code generation + worktree execution
├── github.py            # GitHub PR/issue integration
├── agent_config.py      # Agent config file detection (AGENTS.md, .cursorrules, etc.)
├── mcp.py               # MCP client — connects to external tool servers
├── llm.py               # LLM model info helpers + async retry wrapper
└── utils.py             # Async subprocess (arun), git helpers, timestamps

tests/
├── conftest.py          # Shared fixtures
├── unit/                # Fast unit tests — all external services mocked
│   ├── test_agent_config.py
│   ├── test_config.py
│   ├── test_discovery.py
│   ├── test_executor.py
│   ├── test_github.py
│   ├── test_ideation.py
│   ├── test_knowledge.py
│   ├── test_llm.py
│   ├── test_maintenance.py
│   ├── test_mcp.py
│   ├── test_memory.py
│   ├── test_utils.py
│   └── test_validation.py
└── integration/         # Integration tests (real LLM API calls via litellm)
    ├── conftest.py      # Provider registry, make_config(), tiny_repo fixture
    ├── test_memory.py   # Memory lifecycle across runs
    └── test_pipeline.py # Real pipeline stage tests across all providers

.github/
└── workflows/
    ├── ci.yml           # Lint + unit tests on every push (Python 3.11/3.12/3.13)
    ├── integration.yml  # Provider integration tests weekly + on-demand
    └── sigil.yml        # Dogfood: runs Sigil on itself daily at 02:00 UTC

examples/
├── github-action.yml         # Reusable action workflow
└── github-action-manual.yml  # Manual setup variant

action.yml               # Composite GitHub Action (uses: dylan-murray/sigil@main)

.sigil/                  # Runtime directory (created on first run)
├── config.yml           # User configuration
├── memory/              # Persistent knowledge base
│   ├── INDEX.md         # Knowledge index (HEAD SHA + per-file descriptions)
│   ├── working.md       # Operational history (managed by memory.py)
│   └── *.md             # Topic knowledge files
└── ideas/               # Feature idea storage
    └── *.md             # Individual idea files with YAML frontmatter

.issues/                 # Issue tracker (gitignored from public repo)
├── INDEX.md             # Issue index
├── current-sprint.md    # Active sprint
├── pm-context.md        # PM decisions and context
└── sprints/             # Sprint archives
    ├── sprint-6.md
    └── sprint-7.md

.closed_issues/          # Closed issue archive
```

## Current Status

Phase 1 MVP pipeline is complete. All 24 Phase 1 tickets closed. Extensibility track complete (MCP client support, tool naming, deferred loading). Quality track complete (CI on push, integration CI weekly, full unit test coverage across all modules). Sprint 7 complete (parallel-agent validation + per-agent model configuration). Dogfood CI added (Sigil runs on itself daily).

- **CI:** GitHub Actions runs lint + unit tests on every push (Python 3.11/3.12/3.13); integration tests run weekly across 6 providers; Sigil runs on itself daily via `sigil.yml`
- **MCP:** Sigil connects to external MCP servers (stdio + SSE), tools namespaced as `mcp__server__tool`
- **Validation:** Single mode (default) or parallel mode (two reviewers + arbiter)
- **Per-agent models:** Each agent can use a different model via `agents` config; `fast_model` deprecated
- **Sprint archives:** Completed sprints archived in `.issues/sprints/sprint-N.md`

## Key Constraints / Hard Rules

- **NEVER commit without running `/commit-review` first** (project rule)
- **NEVER write tests directly** — use `/test-writer` skill
- **Run `uv run ruff format .` as the LAST step** after ALL code changes
- No comments in code unless logic is genuinely non-obvious
- CLI + GitHub Action, tested across 6 LLM providers
- Every PR opened must have CI passing before merge is suggested
- Conservative by default — when in doubt, open an issue not a PR
- Respect existing agent config files in target repos (AGENTS.md, CLAUDE.md, .cursorrules, etc.)
- Copy existing patterns (Claude Code, Agent SDK, Codex) — don't reinvent the wheel

## Issue Tracker

Issues live in `.issues/` (gitignored from public repo). Closed issues in `.closed_issues/`. Sprint history in `.issues/sprints/`. The `/pm` skill manages issue lifecycle.

## Known Bugs (from working memory)

- `execute_parallel` uses `""` as sentinel for "no branch" — should be `str | None`
- `apply_edit` has no guard against empty `old_content` (potential full-file replacement)
- `MODEL_OVERRIDES` in `llm.py` may be dead code (no tests verify it's used)
- Package not yet published to PyPI (GitHub Action example uses git install from `main`)
