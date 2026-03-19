head: 26aed4e0d4fa5b48f822180b7c91c8ce4eff24ae
last_updated: 2026-03-19T04:19:08Z

# Sigil — Autonomous Repo Improvement Agent

## What It Is

Sigil is a proactive AI agent that watches repositories, finds improvements, and ships pull requests automatically. Unlike reactive tools triggered by humans, Sigil runs on a schedule (via GitHub Actions or cron), analyzes codebases, and opens small PRs for low-risk improvements while creating issues for high-risk findings.

**Target users:** Development teams who want continuous, automated code improvements without manual intervention.

## Architecture

### Core Components

- **CLI (`sigil/cli.py`)** — Main entrypoint with `init`, `run`, `watch` commands
- **Discovery (`sigil/discovery.py`)** — Analyzes repo structure, reads source files, builds context for LLM
- **Memory (`sigil/memory.py`)** — Persistent knowledge storage in `.sigil/memory/` (project understanding + working history)
- **Config (`sigil/config.py`)** — YAML-based configuration with model, boldness, focus areas
- **LLM (`sigil/llm.py`)** — Model-agnostic interface via litellm

### Memory System

Sigil maintains persistent memory in `.sigil/memory/`:
- `project.md` — Deep project understanding (LLM-compacted)
- `working.md` — Run history, attempts, learnings (LLM-compacted)

**Critical:** Memory files are committed and may be public. Never store secrets.

### Discovery Process

1. Detects language, CI, file structure
2. Reads package manifests (pyproject.toml, package.json, etc.)
3. Analyzes recent commits for context
4. Summarizes source files within token budget
5. Feeds everything to LLM for structured analysis

## Tech Stack

- **Language:** Python 3.11+
- **CLI:** typer + rich for beautiful terminal output
- **LLM:** litellm (supports Anthropic, OpenAI, Gemini, etc.)
- **Git:** GitPython for repo operations
- **Config:** PyYAML for configuration
- **Package manager:** uv (modern Python packaging)

## Key Dependencies

```toml
typer>=0.15        # CLI framework
litellm>=1.60      # LLM abstraction
PyGithub>=2.6      # GitHub API
pyyaml>=6.0        # Config parsing
rich>=13.0         # Terminal formatting
gitpython>=3.1     # Git operations
```

## Usage Patterns

### Basic Workflow
```bash
sigil init --repo .           # Creates .sigil/config.yml
sigil run --repo .            # Analyzes repo, opens PRs/issues
```

### Configuration
```yaml
version: 1
model: anthropic/claude-sonnet-4-20250514
boldness: bold               # conservative | balanced | bold | experimental
focus: [tests, dead_code, security, docs, types, features]
max_prs_per_run: 3
schedule: "0 2 * * *"
```

### GitHub Action Integration
Runs on schedule with `contents: write` and `pull-requests: write` permissions.

## Coding Conventions

- **No comments** unless explicitly requested
- **Type hints** with `from __future__ import annotations`
- **Dataclasses** with `frozen=True, slots=True` for immutable config
- **Path objects** instead of strings for file operations
- **Rich console** for all user-facing output
- **Error handling** with typer.Exit() for CLI errors

## Development Commands

```bash
# Setup
uv sync

# Format (ALWAYS run as final step)
uv run ruff format .

# Run locally
uv run sigil init --repo .
uv run sigil run --repo .

# Install as tool
uv tool install .
```

## Design Decisions

1. **LLM-agnostic:** Uses litellm to support any provider (user brings API key)
2. **Memory persistence:** Avoids re-analyzing unchanged repos
3. **Token budget management:** Summarizes large codebases to fit context windows
4. **Proactive not reactive:** Runs on schedule, not on events
5. **Small PRs:** Focuses on low-risk improvements to minimize review burden
6. **Open source core:** Phase 1 is fully open source, Phase 2 adds hosted platform

## Current State

Early development (v0.1.0). Core discovery and memory systems implemented. Next: actual PR/issue creation logic, GitHub integration, and CI workflows.

Recent focus: Memory system with LLM-compacted knowledge, source code analysis with token budgeting, and repository discovery pipeline.