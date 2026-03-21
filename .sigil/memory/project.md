# Project Overview — Sigil

## What is Sigil?

Sigil is an autonomous repository improvement agent that proactively finds improvements and ships pull requests while you sleep. It runs on a schedule, analyzes the codebase, and opens small, safe PRs for low-risk improvements. High-risk findings become GitHub issues.

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

## How to Build/Test/Lint

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
```

## Project Structure

```
sigil/
├── __init__.py          # Version: 0.1.0
├── __main__.py          # Entry point
├── cli.py               # CLI commands + main pipeline orchestration
├── config.py            # Config loading/validation
├── discovery.py         # Repo structure reading
├── knowledge.py         # Knowledge compaction + selection
├── memory.py            # Working memory management
├── maintenance.py       # Maintenance analysis agent
├── ideation.py          # Feature ideation agent
├── validation.py        # Finding/idea validation agent
├── executor.py          # Code generation + worktree execution
├── github.py            # GitHub PR/issue integration
├── llm.py               # LLM model info helpers
└── utils.py             # Async subprocess, git helpers

tests/
├── conftest.py
├── unit/                # Fast unit tests (mocked)
└── integration/         # Integration tests (real services)

examples/
└── github-action.yml    # GitHub Action workflow template

.sigil/                  # Runtime directory (created on first run)
├── config.yml           # User configuration
├── memory/              # Persistent knowledge base
│   ├── INDEX.md         # Knowledge index
│   ├── working.md       # Operational history
│   └── *.md             # Topic knowledge files
└── ideas/               # Feature idea storage
    └── *.md             # Individual idea files
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

Phase 1 MVP pipeline is complete. 108 tests passing. Full async pipeline, no tree-sitter dependency. Ready for dogfooding (issue #010).

Open issues: #010 (dogfood on real repo). Phase 2 backlog: #011-015, #025-026.
