head: 62ded8d1b367e2adbd36c30039555790d7f24c40
last_updated: 2026-03-19T03:54:50Z

# Sigil — Autonomous Repo Improvement Agent

## What It Is

Sigil is a proactive AI agent that continuously monitors code repositories, identifies improvements, and automatically ships pull requests. Unlike reactive tools that wait for human triggers, Sigil runs on a schedule (typically nightly) to find and fix issues like missing tests, dead code, security vulnerabilities, documentation gaps, and type annotations.

**Target Users:** Development teams who want continuous, automated code quality improvements without manual intervention.

## Architecture

### Core Components

- **CLI (`sigil/cli.py`)** — Main entrypoint with `init`, `run`, and `watch` commands
- **Discovery (`sigil/discovery.py`)** — Analyzes repository structure and builds understanding via LLM
- **Memory (`sigil/memory.py`)** — Persistent cache system to avoid re-analyzing unchanged code
- **LLM Integration (`sigil/llm.py`)** — Abstraction over litellm for multi-provider AI access
- **Models (`sigil/models.py`)** — Data structures for repository representation
- **Config (`sigil/config.py`)** — YAML-based configuration management

### Data Flow

1. **Discovery** — Scans repo files, builds `RepoModel` via LLM analysis
2. **Memory** — Caches findings in `.sigil/memory/` to avoid redundant work
3. **Analysis** — LLM identifies improvements based on configured focus areas
4. **Action** — Low-risk findings become PRs, high-risk become issues

## Technology Stack

- **Language:** Python 3.11+
- **Package Manager:** uv (modern, fast Python packaging)
- **CLI Framework:** Typer
- **LLM Provider:** litellm (supports Anthropic, OpenAI, Gemini, etc.)
- **Git Integration:** GitPython + PyGithub
- **Config Format:** YAML

## Configuration

Lives in `.sigil/config.yml` after `sigil init`:

```yaml
version: 1
model: anthropic/claude-sonnet-4-20250514
boldness: bold  # conservative | balanced | bold | experimental
focus: [tests, dead_code, security, docs, types, features]
max_prs_per_run: 3
schedule: "0 2 * * *"
```

## Development Workflow

### Setup
```bash
uv sync                    # Install dependencies
uv run sigil --help        # Test CLI
```

### Code Standards
- **Formatting:** `uv run ruff format .` (required after changes)
- **Style:** No comments unless explicitly needed
- **Line Length:** 100 characters
- **Quotes:** Double quotes

### Memory System
Persistent cache in `.sigil/memory/`:
- `repo-model.json` — Repository structure understanding
- `findings.json` — Previous analysis results
- `features.json` — Discovered capabilities
- `runs.json` — Execution history

## Deployment

### GitHub Action
Runs on schedule with repository write permissions:
```yaml
- run: sigil run --repo . --ci
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Local Usage
```bash
sigil init --repo .
sigil run --repo .
```

## Design Decisions

- **Proactive vs Reactive:** Runs on schedule, not triggered by events
- **Multi-LLM:** Uses litellm for provider flexibility
- **Persistent Memory:** Caches analysis to avoid redundant LLM calls
- **Risk-Based Actions:** PRs for safe changes, issues for risky ones
- **Open Source Core:** CLI tool is free, hosted platform planned for Phase 2

## Business Model

Phase 1 (current): Open source tool using user's API keys
Phase 2 (planned): Hosted SaaS with cross-repo learning, dashboard, integrations