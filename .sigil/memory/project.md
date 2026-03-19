head: 2744e3c191bfce435f2ef315c752d295e5fa32b6
last_updated: 2026-03-19T04:36:25Z

# Sigil — Autonomous Repo Improvement Agent

## Overview

Sigil is a proactive AI agent that autonomously analyzes code repositories, identifies improvements, and ships pull requests on a schedule. Unlike reactive tools, Sigil runs continuously in CI, finding and fixing issues before humans notice them.

**Target users:** Development teams who want automated code quality improvements without manual intervention.

**Key value:** Proactive vs reactive — finds problems and ships fixes while you sleep.

## Architecture

### Core Components

- **CLI (`cli.py`)** — Entry points: `sigil init`, `sigil run`, `sigil watch`
- **Discovery (`discovery.py`)** — Analyzes repo structure, reads source files, builds context
- **Memory (`memory.py`)** — Persistent LLM-compacted knowledge in `.sigil/memory/`
- **LLM (`llm.py`)** — Model-agnostic interface via litellm
- **Config (`config.py`)** — YAML-based configuration with focus areas and boldness levels

### Memory System

Sigil maintains persistent memory in `.sigil/memory/`:
- `project.md` — Deep understanding of the project (this file)
- `working.md` — Run history, what Sigil has tried and learned

Memory is LLM-compacted to stay within context windows and committed to the repo.

### Discovery Engine

Smart file analysis with budget allocation:
- Detects language, CI, package manifests automatically
- Summarizes source files with language-specific parsers
- Scales token budget based on model context window
- Prioritizes recent commits and source files over config

## Technology Stack

- **Language:** Python 3.11+
- **Dependencies:** typer (CLI), litellm (LLM), PyGithub (Git), rich (UI), pyyaml, gitpython
- **Package manager:** uv (`uv sync`, `uv add`, `uv run`)
- **LLM providers:** Any via litellm (Anthropic, OpenAI, Gemini, etc.)

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

### Commands
- **Install deps:** `uv sync`
- **Run locally:** `uv run sigil run --repo .`
- **Format code:** `uv run ruff format .` (ALWAYS run after code changes)
- **Add deps:** `uv add <package>`

### Coding Conventions
- No comments unless explicitly requested
- Use `from __future__ import annotations` in all files
- Dataclasses with `frozen=True, slots=True` for config
- Rich console for CLI output
- Type hints required (Python 3.11+ syntax)

### File Organization
- `sigil/` — Main package
- `.sigil/memory/` — Persistent memory (committed, public-safe)
- Entry point: `sigil.cli:app`

## Key Design Decisions

1. **Model-agnostic:** Uses litellm so users can choose any LLM provider
2. **Memory persistence:** Compacted knowledge survives across runs
3. **Budget-aware discovery:** Scales analysis to model context limits
4. **Language-specific summarization:** Python classes/functions, JS/TS exports, generic fallback
5. **Public-safe memory:** No secrets in committed memory files

## Current State

Recent development focused on smart discovery and memory systems:
- Smart Python summarizer captures class shapes and key functions
- Discovery engine scales token budget per model context window
- Memory system with staleness detection and LLM compaction
- Source file prioritization over config files

The tool is in Phase 1 (CLI tool) with plans for Phase 2 (hosted platform with cross-repo learning).

## Deployment

GitHub Action runs on schedule:
```yaml
- run: uv tool install sigil
- run: sigil run --repo . --ci
```

Users bring their own API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.).