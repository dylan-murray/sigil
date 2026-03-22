---
last_updated: '2026-03-22T05:16:01Z'
---

# Sigil Working Memory

## Repository Overview
Sigil's own repository — an AI agent for code analysis and improvement. Modern Python structure (pyproject.toml, src layout), type hints throughout, partially implemented test infrastructure. Early-stage but actively improving. Self-hosting CI active.

## What Has Been Done

### PRs Opened
- **#1–#3**: Git config fix, instructions.md, `sigil status` command
- **#16–#20**: Ignore config globs, CI self-hosting, knowledge selection caching, rebase diagnostics, README/LICENSE
- **#27–#30**: Pre-flight validation, knowledge diff annotations, JSON schema export, PR template customization
- **#36**: Commit Message Archaeology — mine git history narrative to surface developer intent
- **#37**: Sigil Config Profiles — named configuration presets for different run contexts
- **#38**: Knowledge File Health Metrics — track staleness, size, and access frequency per knowledge file

### Issues Filed
- **#4–#13**: Integration test gaps, `execute_parallel` sentinel, dead code, model mismatch, GitHub Action, human-in-the-loop, cross-agent knowledge, adversarial validation, versioning, PR review
- **#21–#25**: `execute_parallel` sentinel (confirmed), `memory.py` coverage, `cli.py` coverage, counterfactual refactoring, path-scoped runs
- **#31–#35**: Won't-Fix registry, execution agent specialization, run history log, knowledge quality validation, dependency-aware work item ordering
- **#39**: Diff-Level Validation — verify generated diffs are syntactically valid before committing
- **#40**: PR Comment Mining — learn from human reviewer patterns to calibrate future proposals
- **#41**: Finding Confidence Scores — LLM self-rates certainty to drive disposition thresholds
- **#42**: Idea Genealogy — track which ideas spawned which PRs, build dependency graph
- **#43**: Execution Sandbox Mode — run lint/tests in Docker for untrusted repos

## Open Validated Findings Not Yet Acted On
- **`apply_edit` empty `old_content` guard** — `"" in any_string` is always `True`; allows arbitrary content prepending. **High priority — PR not yet opened.**
- **`execute_parallel` `""` sentinel** — filed as #21; return type should be `str | None`. **High priority — PR not yet opened.**
- **`DEFAULT_MODEL` mismatch** — `config.py` model name never matches `MODEL_OVERRIDES` keys (date-suffixed); `configuration.md` documents yet another name. **Medium priority.**
- **`memory.py` zero test coverage** — `load_working`/`update_working` untested. **Medium priority.**
- **`cli.py` zero test coverage** — `_format_run_context` is a pure function, trivially testable. **Medium priority.**

## Patterns Learned
- Test suite uses real git repos via `tmp_path` — requires explicit git config (`user.email`/`user.name`)
- `"" in any_string` is always `True` — the `apply_edit` empty `old_content` bug is subtle but real
- `MODEL_OVERRIDES` keys use date suffixes; default model name never matches, always falls through to litellm
- No integration tests despite scaffolded directory; unit coverage gaps persist in `memory.py` and `cli.py`
- Rebase failures have been stable — PR #19 diagnostics appear to be helping
- PRs #36–#38 each required 1 retry — executor LLM may benefit from warm-up (issue #43 area)

## Next Run Focus
1. **High Priority**: Open PR for `apply_edit` empty `old_content` guard (`sigil/executor.py`)
2. **High Priority**: Open PR for `execute_parallel` `str | None` sentinel fix (`sigil/executor.py`)
3. **Medium Priority**: Sync `DEFAULT_MODEL` across `config.py`, `llm.py` `MODEL_OVERRIDES`, and `configuration.md`
4. **Medium Priority**: Add tests for `memory.py` (`load_working`, `update_working`)
5. **Medium Priority**: Add tests for `cli.py` (`_format_run_context` at minimum)
6. **Low Priority**: Smoke-level tests for `llm.py` and `github.py`

## Notes
- No user rejections recorded across all runs
- Self-hosting CI active (PR #17) — Sigil runs on its own repo automatically
- Feature surface now includes: README, LICENSE, PR templates, JSON schema, knowledge diffs, pre-flight validation, config profiles, knowledge health metrics, commit archaeology
