```markdown
head: 3f7fe61aeb620a734b21db7c3f7d120b7c46fb61
last_updated: 2026-03-19T04:29:25Z

# Sigil — Autonomous Repo Improvement Agent

## What It Is

Sigil is a proactive AI agent that autonomously analyzes code repositories, identifies improvements, and ships pull requests on a schedule. Unlike reactive tools that wait for human triggers, Sigil runs continuously (via CI cron jobs) to find and fix issues like missing tests, dead code, security vulnerabilities, documentation gaps, and type annotations.

**Target users:** Development teams who want continuous, automated code quality improvements without manual intervention.

## Tech Stack

- **Language:** Python 3.11+
- **Package manager:** uv (modern Python packaging)
- **CLI framework:** typer + rich (for beautiful terminal output)
- **LLM integration:** litellm (model-agnostic, supports Anthropic, OpenAI, Gemini, etc.)
- **Git operations:** GitPython
- **GitHub integration:** PyGithub
- **Config format:** YAML

## Architecture

### Core Components

1. **CLI (`cli.py`)** — Entry point with `init`, `run`, `watch` commands
2. **Discovery (`discovery.py`)** — Analyzes repo structure, reads source files, builds context
3. **Memory (`memory.py`)** — Persistent knowledge storage in `.sigil/memory/`
4. **Config (`config.py`)** — User configuration in `.sigil/config.yml`
5. **LLM (`llm.py`)** — Model-agnostic completions via litellm
6. **Utils (`utils.py`)** — Git operations and utilities

### Memory System

Sigil maintains persistent memory in `.sigil/memory/`:
- `project.md` — Deep understanding of the project (LLM-compacted)
- `working.md` — What Sigil has done, tried, learned (LLM-compacted)

**Critical constraint:** Memory files are committed and may be public — never store secrets.

### Discovery Process

1. Detects language, CI system, file structure
2. Reads package manifests (pyproject.toml, package.json, etc.)
3. Intelligently samples source files based on model context window
4. Summarizes file contents (imports, structure, key functions)
5. Builds comprehensive repo context for LLM analysis

## Configuration

Users configure via `.sigil/config.yml`:
```yaml
model: anthropic/claude-sonnet-4-20250514
boldness: bold  # conservative | balanced | bold | experimental
focus: [tests, dead_code, security, docs, types, features]
max_prs_per_run: 3
schedule: "0 2 * * *"
```

## Key Design Decisions

1. **Model-agnostic:** Uses litellm to support any LLM provider
2. **Smart discovery:** Adapts file sampling to model context windows
3. **Memory persistence:** Avoids re-analyzing unchanged repos
4. **Security-first:** Never stores secrets in committed memory files
5. **Proactive scheduling:** Runs on cron, not human triggers

## Development Workflow

### Commands
```bash
# Install dependencies
uv sync

# Format code (ALWAYS run after code changes)
uv run ruff format .

# Run locally
uv run sigil init --repo .
uv run sigil run --repo .
```

### Coding Conventions
- No comments unless explicitly needed
- Use `from __future__ import annotations` in all files
- Dataclasses with `frozen=True, slots=True` for config objects
- Rich console output for user-facing messages
- Type hints required (Python 3.11+ syntax)

### Memory Management Rules
- Update `.sigil/memory/project.md` after architectural changes
- Delete memory files to force regeneration if they become stale
- Memory must always reflect current code state
- Never commit sensitive information to memory

## Recent Development

Latest commits show progression through discovery system improvements:
- Smart file sampling based on model context windows
- Source code summarization for different languages
- Memory system with LLM-compacted knowledge storage
- Persistent discovery caching to avoid re-analysis

The project is in Phase 1 (CLI tool) with plans for Phase 2 (hosted platform with cross-repo learning).

## Installation & Usage

```bash
# Install
uv tool install sigil

# Initialize in repo
sigil init --repo .

# Run analysis
sigil run --repo .

# GitHub Action integration available
```

Users bring their own API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.).
```