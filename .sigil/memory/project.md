---
head: fe123c6018b4b438d9547c06f72c22ca1e984610
last_updated: '2026-03-19T04:42:15Z'
---

# Sigil — Autonomous Repo Improvement Agent

## Overview

Sigil is a proactive AI agent that autonomously analyzes code repositories, identifies improvements, and ships pull requests on a schedule. Unlike reactive tools that wait for human triggers, Sigil runs continuously in CI to find and fix issues like missing tests, dead code, security vulnerabilities, documentation gaps, and type annotations.

**Target users:** Development teams who want automated code quality improvements without manual intervention.

## Architecture

### Core Components

- **CLI (`sigil/cli.py`)** — Main entrypoint with `init`, `run`, and `watch` commands
- **Discovery (`sigil/discovery.py`)** — Analyzes repository structure, reads source files, and builds context for LLM analysis
- **Memory (`sigil/memory.py`)** — Persistent knowledge storage in `.sigil/memory/` with LLM-compacted markdown files
- **Config (`sigil/config.py`)** — YAML-based configuration for model, focus areas, and behavior settings
- **LLM (`sigil/llm.py`)** — Model-agnostic interface using litellm for any provider (Anthropic, OpenAI, Gemini, etc.)

### Data Flow

1. **Discovery** scans repo, reads source files with smart summarization, respects token budgets per model
2. **Memory** loads/updates persistent project knowledge and working context
3. **LLM** analyzes findings and generates improvement recommendations
4. **Output** creates PRs for low-risk changes, issues for high-risk findings

## Technology Stack

- **Language:** Python 3.11+
- **Package Manager:** uv (`uv sync`, `uv add`, `uv run`)
- **CLI Framework:** typer + rich for beautiful terminal output
- **LLM Integration:** litellm (supports 100+ providers)
- **Git Operations:** GitPython + PyGithub for repository manipulation
- **Config Format:** YAML via PyYAML

## Key Features

### Smart Discovery
- Language detection (Python, JavaScript/TypeScript, etc.)
- CI detection (GitHub Actions, etc.)
- Source file summarization with token budget management
- Skips irrelevant files (node_modules, .git, build artifacts)

### Memory System
- **`.sigil/memory/project.md`** — Deep project understanding (LLM-compacted)
- **`.sigil/memory/working.md`** — Run history and learnings (LLM-compacted)
- Staleness detection based on git HEAD changes
- Automatic compaction to prevent memory bloat

### Configuration
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
- **No comments** unless explicitly requested
- **Always run `uv run ruff format .`** as the LAST step after ALL code changes
- Use `from __future__ import annotations` in all files
- Dataclasses with `frozen=True, slots=True` for immutable config
- Type hints required (Python 3.11+ syntax)

### Testing & Quality
```bash
uv run ruff format .       # Format code (REQUIRED after changes)
uv run ruff check .        # Lint (when available)
```

## Design Decisions

### Token Budget Management
Discovery dynamically allocates token budget based on model context windows:
- Claude Sonnet: 200k context → 30k source tokens
- GPT-4: 128k context → 20k source tokens  
- Reserves tokens for prompts (8k) and responses (4k)

### File Summarization
- **Python:** Extracts imports, classes with fields/methods, top-level functions
- **JS/TS:** Extracts imports/exports, classes, functions, types
- **Generic:** First/last lines + size for other file types
- Respects 3k character limit per file to prevent token explosion

### Memory Persistence
- Committed to repository (may be public — NO SECRETS)
- LLM-compacted to prevent unbounded growth
- Frontmatter tracks metadata (last_updated, git_head)
- Regenerated when stale (git HEAD changed)

## Current State

**Phase 1 (Tool)** — Core CLI functionality complete:
- ✅ Project scaffolding and configuration
- ✅ Repository discovery with smart file reading
- ✅ Persistent memory system with LLM compaction
- ✅ Model-agnostic LLM integration
- 🚧 **Next:** Actual improvement detection and PR generation

**Planned:** GitHub Action integration, issue creation, improvement analysis engine.
