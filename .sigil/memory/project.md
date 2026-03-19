head: 78ec7170455b427a00bb9b80762e8f2baeaa33d4
last_updated: 2026-03-19T04:11:27Z

# Sigil — Autonomous Repo Improvement Agent

## What It Is

Sigil is a proactive AI agent that watches repositories, finds improvements, and ships pull requests automatically. Unlike reactive tools triggered by humans, Sigil runs on a schedule (via GitHub Actions or cron) and opens small, safe PRs for low-risk improvements while creating issues for high-risk findings.

**Target users:** Development teams who want continuous, automated code improvements without manual intervention.

## Architecture

### Core Components

- **CLI (`sigil.cli`)** — Typer-based interface with `init`, `run`, `watch` commands
- **Discovery (`sigil.discovery`)** — Analyzes repo structure, detects language/CI, reads source files
- **Memory (`sigil.memory`)** — Persistent LLM-compacted knowledge in `.sigil/memory/`
- **Config (`sigil.config`)** — YAML-based configuration with boldness levels and focus areas
- **LLM (`sigil.llm`)** — Model-agnostic completions via litellm

### Memory System

Sigil maintains persistent memory in `.sigil/memory/`:
- `project.md` — Deep understanding of the project (this file)
- `working.md` — What Sigil has done, tried, learned across runs

Memory is LLM-compacted to stay fixed-size and committed to the repo. **Never stores secrets.**

### Configuration

`.sigil/config.yml` controls behavior:
- **model** — Any litellm-supported model (anthropic/claude-sonnet-4-20250514 default)
- **boldness** — conservative | balanced | bold | experimental
- **focus** — tests, dead_code, security, docs, types, features
- **limits** — max PRs/issues per run

## Language & Stack

- **Python 3.11+** with uv for dependency management
- **Dependencies:** typer (CLI), litellm (LLM), PyGithub (Git ops), rich (output), GitPython, PyYAML
- **Code style:** Ruff formatting, no comments unless explicitly needed
- **Entry point:** `sigil.cli:app` script

## Commands

```bash
# Setup
uv sync                    # Install dependencies
uv add <package>          # Add dependency

# Usage
sigil init --repo .       # Initialize config
sigil run --repo .        # Analyze and open PRs
sigil run --dry-run       # Analyze only
sigil watch               # Scheduled runs (not implemented)

# Development
uv run ruff format .      # Format code (ALWAYS run last after changes)
```

## Current State

**Phase 1 (Tool)** — Core CLI and discovery complete:
- ✅ Project scaffold with CLI framework
- ✅ Config system with YAML persistence  
- ✅ Repository discovery (language detection, file analysis, git integration)
- ✅ LLM-compacted memory system with staleness detection
- 🚧 Analysis phase (finding improvements) — not implemented
- 🚧 Codegen phase (creating PRs/issues) — not implemented
- 🚧 Watch mode for local scheduling — not implemented

**Phase 2 (Platform)** — Planned hosted SaaS with dashboard, cross-repo learning, integrations.

## Key Patterns

- **Immutable config** — `@dataclass(frozen=True)` with factory defaults
- **Path resolution** — Always resolve repo paths for consistent git operations
- **Error handling** — Graceful fallbacks for git/file operations with timeouts
- **Memory staleness** — Compare git HEAD to detect when discovery is needed
- **Budget limits** — Truncate large files/outputs to stay within LLM context windows
- **No secrets rule** — Memory files are public-safe, never store credentials

## Recent Activity

Recent commits show progression through memory system implementation (003), discovery module (002), and initial scaffold (001). The project is in active development with core infrastructure complete and analysis/codegen phases next.