---
head: fa31effb196d60570a377732940636e5dabfe9fb
last_updated: '2026-03-19T05:42:40Z'
---

# Sigil — Autonomous Repo Improvement Agent

## Overview

Sigil is a proactive AI agent that autonomously analyzes code repositories, identifies improvements, and ships pull requests on a schedule. Unlike reactive tools that wait for human triggers, Sigil runs continuously in CI, opening PRs for low-risk improvements and issues for high-risk findings.

**Target users:** Development teams who want automated code quality improvements without manual intervention.

## Architecture

### Core Components

- **CLI (`sigil/cli.py`)** — Main entrypoint with `init`, `run`, `watch` commands
- **Discovery (`sigil/discovery.py`)** — Analyzes repo structure, detects language/CI, reads source files with smart budgeting
- **Memory (`sigil/memory.py`)** — Persistent knowledge storage in `.sigil/memory/` with LLM-compacted markdown
- **LLM (`sigil/llm.py`)** — Model-agnostic interface via litellm
- **Config (`sigil/config.py`)** — YAML-based configuration with boldness levels and focus areas

### Memory System

Sigil maintains persistent state in `.sigil/memory/`:
- `project.md` — Deep project understanding (this file)
- `working.md` — Run history, attempts, learnings

Memory uses YAML frontmatter for metadata and is LLM-compacted to stay current.

### Discovery Engine

Smart repo analysis that:
- Detects language from file extensions and package manifests
- Identifies CI systems (GitHub Actions, etc.)
- Reads source files with token budget allocation per model
- Summarizes code structure using tree-sitter parsing
- Skips common ignore patterns (node_modules, .git, etc.)

## Technology Stack

- **Language:** Python 3.11+
- **CLI:** typer + rich for beautiful terminal output
- **LLM:** litellm for model-agnostic API calls
- **Git:** GitPython for repository operations
- **Parsing:** tree-sitter for code analysis
- **Package management:** uv (modern pip replacement)

### Key Dependencies

```toml
typer>=0.15          # CLI framework
litellm>=1.60        # LLM abstraction
PyGithub>=2.6        # GitHub API
pyyaml>=6.0          # Config parsing
rich>=13.0           # Terminal UI
gitpython>=3.1       # Git operations
tree-sitter==0.21.3  # Code parsing
```

## Configuration

After `sigil init`, configure `.sigil/config.yml`:

```yaml
version: 1
model: anthropic/claude-sonnet-4-20250514
boldness: bold  # conservative | balanced | bold | experimental
focus: [tests, dead_code, security, docs, types, features]
max_prs_per_run: 3
max_issues_per_run: 5
schedule: "0 2 * * *"
```

## Development Workflow

### Setup
```bash
uv sync                    # Install dependencies
uv run sigil --help       # Test CLI
```

### Code Standards
- No comments unless explicitly requested
- Use dataclasses with `frozen=True, slots=True` for immutable data
- Type hints required for public APIs
- Rich console output for user-facing messages

### Formatting
```bash
uv run ruff format .       # ALWAYS run as final step after code changes
```

### Testing
Currently no test suite — early development phase.

## Design Decisions

### Model Agnostic
Uses litellm to support any LLM provider (Anthropic, OpenAI, Gemini, etc.). Users bring their own API keys.

### Token Budget Management
Discovery engine allocates token budget based on model context windows:
- Claude: 150k tokens for source files
- GPT-4: 100k tokens for source files  
- Reserves tokens for prompts and responses

### Memory Persistence
Stores compressed knowledge in repo (not external DB) for simplicity and transparency. Memory files are committed and may be public.

### Security Guardrails
- Never stores secrets in memory files
- Memory prompts explicitly warn against including credentials
- All sensitive data comes from environment variables

## Business Model

Open source CLI tool with planned hosted SaaS platform featuring:
- Managed infrastructure (no API keys needed)
- Cross-repo learning and fine-tuned models
- Dashboard and run history
- Team collaboration features

## Current State

Early development (v0.1.0). Core discovery and memory systems implemented. Next priorities:
- Actual improvement detection and PR generation
- GitHub integration for automated PRs
- Scheduling and CI integration
