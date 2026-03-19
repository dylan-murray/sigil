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
- Uses the user's own Claude API key
- Open source
- Opens PRs for low-risk improvements, issues for high-risk findings

### Phase 2 — The Platform
- Hosted version (no API key needed)
- Dashboard + run history
- Cross-repo learning / fine-tuned model trained on patterns across repos
- Connectors: Linear, Slack, Jira, PagerDuty
- Teams + orgs + SSO

## Business Model

Open source core + hosted SaaS. Self-hosting is possible but the platform
value (cross-repo learning, dashboard, connectors, managed infra) drives
paid conversion.

## Issue Tracker

Issues live in `.issues/`. See `.issues/README.md` for the index.
The `/pm` skill manages issue lifecycle.

## Code Standards

- Language: Python (uv for deps)
- CLI framework: TBD (likely typer or click)
- No comments unless explicitly asked
- Run `uv run ruff format .` after all code changes

## Dependencies

Managed by `uv`: `uv sync`, `uv add <pkg>`, `uv run <cmd>`.
