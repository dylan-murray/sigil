# Project: Sigil — Autonomous Repo Improvement Agent

## What is Sigil?

Sigil is a proactive, scheduled AI agent that watches your repository, finds
improvements, and ships pull requests — without being asked. It runs in CI on
a schedule, analyzes the codebase, and opens small, safe PRs for low-risk
improvements. High-risk findings become issues.

**The gap it fills:** Every tool today is reactive (triggered by humans) or
narrow (only deps, only reviews). Sigil is proactive and general-purpose.

## Product Phases

### Phase 1 — The Tool (current focus)
- CLI entrypoint: `sigil init`, `sigil run`, `sigil watch`
- GitHub Action that runs on a schedule
- LLM-agnostic via litellm (user brings their own API key + model)
- Open source
- Opens PRs for low-risk improvements, issues for high-risk findings

### Phase 2 — The Platform
- Hosted version (no API key needed, memory stored in cloud)
- Dashboard + run history
- Cross-repo learning / fine-tuned model trained on patterns across repos
- Connectors: Linear, Slack, Jira, PagerDuty
- MCP server integration (Notion, Snowflake, Databricks, etc.)
- Teams + orgs + SSO

## Business Model

Open source core + hosted SaaS. Self-hosting is possible but the platform
value (cross-repo learning, dashboard, connectors, managed infra) drives
paid conversion.

## Issue Tracker

Issues live in `.issues/`. See `.issues/INDEX.md` for the index.
The `/pm` skill manages issue lifecycle, sprint planning, and prioritization.
A post-commit hook checks if open issues should be closed after each commit.

## Code Standards

- Language: Python 3.11+ (uv for deps)
- CLI framework: typer + rich
- LLM calls: litellm (model-agnostic)
- No comments unless explicitly asked
- Run `uv run ruff format .` as the LAST step after ALL code changes

## Dependencies

Managed by `uv`: `uv sync`, `uv add <pkg>`, `uv run <cmd>`.

## Memory System

Sigil maintains persistent memory in `.sigil/memory/`:
- `project.md` — deep understanding of the project (LLM-compacted)
- `working.md` — what Sigil has done, tried, learned (LLM-compacted)

### Critical Rules

- `.sigil/memory/` is committed to the repo and MAY BE PUBLIC
- **NEVER store secrets, API keys, tokens, or credentials in memory files**
- After ANY code change that affects architecture, components, or conventions:
  update `.sigil/memory/project.md` or delete it so the next run regenerates it
- Memory must always reflect the current state of the code — if memory
  conflicts with code, the code is the source of truth
- When deleting or renaming files referenced in memory, update or regenerate memory
