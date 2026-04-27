# Autoresearch: Minimize Token Usage Through Sigil

## Objective
Sigil sends a lot of tokens to LLMs through its system prompts, context prompts, tool schemas, and conversation history. The goal is to minimize the total prompt token burden while preserving functionality and correctness.

## Metrics
- **Primary**: `total_prompt_toks` (unitless, lower is better) — total estimated prompt tokens across all static prompts, tool schemas, and representative agent setups
- **Secondary**: `system_prompt_toks`, `tool_schema_toks`, `context_prompt_toks`

## How to Run
`./autoresearch.sh` — outputs `METRIC total_prompt_toks=...` lines.

## Files in Scope
- `sigil/pipeline/prompts.py` — all system and context prompts (ENGINEER, ARCHITECT, REVIEWER, AUDITOR, IDEATOR, TRIAGER, ARBITER, VALIDATOR, etc.)
- `sigil/pipeline/validation.py` — tool schemas (REVIEW_ITEM_PARAMS, RESOLVE_ITEM_PARAMS)
- `sigil/pipeline/ideation.py` — tool schemas (REPORT_IDEA_PARAMS)
- `sigil/pipeline/maintenance.py` — tool schemas for auditor
- `sigil/pipeline/executor.py` — context building, preloading logic
- `sigil/core/llm.py` — context compaction, masking thresholds, max tokens defaults
- `sigil/core/config.py` — default max_tokens, max_iterations values
- `sigil/core/agent.py` — tool batching instruction, agent setup

## Off Limits
- Test files (tests/)
- CLI formatting, GitHub integrations
- Any changes that break `uv run pytest tests/ -x -q`

## Constraints
- Tests must pass after every change
- No new dependencies
- Functionality must be preserved — only remove redundancy, verbosity, and bloat
- Keep all critical rules and guardrails in prompts

## What's Been Tried
- Baseline measured
