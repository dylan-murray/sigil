# Autoresearch: Sigil Repository

## Repo Summary

**What it does:** Sigil is an autonomous AI coding agent that watches repositories, finds improvements, and ships pull requests automatically. It runs an 8-stage async pipeline (Discover → Learn → Connect MCP → Analyze + Ideate → Validate → Execute → Publish → Remember), with specialized agents for each stage.

**Product code:** The `sigil/` package contains:
- `core/` — LLM wrappers, agents, tools, config, security, models
- `pipeline/` — Pipeline stages: discovery, knowledge, ideation, validation, executor, sandbox
- `state/` — Persistent state: attempts, memory, similarity, chronic
- `integrations/` — GitHub integration for PRs and issues

**Tooling:** Python 3.11+, `uv` for dependency management, `pytest` for tests, `ruff` for lint/format, `litellm` for LLM calls, `typer` + `rich` for CLI.

**Repo health:** 454 unit tests pass in ~5.4s. No broken builds. No TODOs/FIXMEs in product code.

**Recent work:** Autoresearch integration, triager similarity scoring, pydantic validation for engineer tools, LLM hardening (context overflow, structured outputs), arbiter parallel validation.

## Goal

Optimize `find_all_match_locations` in `sigil/core/utils.py`, which is used by the engineer agent's `apply_edit` and `multi_edit` tools.

**Why this matters:** When an edit's `old_content` matches multiple locations in a file, the agent calls `find_all_match_locations` to report line numbers. The current implementation does `content[:idx].count("\n")` for every match — an O(n²) operation over the string prefix. On large files with many repeated patterns (common in generated code, logs, or data files), this causes multi-second pauses on every ambiguous edit attempt.

**Metric:** Wall-clock time of `find_all_match_locations` on a synthetic benchmark (large file with many matches), measured in milliseconds. Lower is better.

**Benchmark scope:** A single function optimization with correctness preserved. The fix should be a single-pass algorithm that tracks line numbers incrementally instead of re-counting from the start each time.
