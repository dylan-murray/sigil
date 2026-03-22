---
last_updated: '2026-03-22T01:09:46Z'
---

# Sigil Working Memory

## Repository Overview
Sigil's own repository — an AI agent for code analysis and improvement. Modern Python structure (pyproject.toml, src layout), type hints throughout, partially implemented test infrastructure. Early-stage but actively improving.

## What Has Been Done

### PRs Opened
- **PR #1**: Fix git config in executor tests
- **PR #2**: Add `.sigil/instructions.md`
- **PR #3**: `sigil status` command
- **PR #16**: Wire `ignore` config field glob patterns into discovery/analysis filtering
- **PR #17**: GitHub Actions CI for Sigil itself (self-hosting)
- **PR #18**: Knowledge selection caching — avoid redundant LLM calls across agents
- **PR #19**: Rebase failure diagnostics — detect and report why rebases fail
- **PR #20**: README and LICENSE
- **PR #27**: Pre-flight validation — run lint+tests before execution to establish baseline
- **PR #28**: Knowledge diff annotations — mark knowledge files with "changed since last run" flags
- **PR #29**: JSON Schema export for `.sigil/config.yml` — IDE autocomplete and validation
- **PR #30**: PR template customization — user-defined PR and issue body templates

### Issues Filed
- **#4–#13**: Integration test gaps, `execute_parallel` sentinel, dead code, model mismatch, GitHub Action, human-in-the-loop, cross-agent knowledge, adversarial validation, versioning, PR review
- **#21–#25**: `execute_parallel` sentinel (confirmed), `memory.py` coverage, `cli.py` coverage, counterfactual refactoring, path-scoped runs
- **#31–#35**: Won't-Fix registry, execution agent specialization, run history log, knowledge quality validation, dependency-aware work item ordering (and others from this run)

## Open Validated Findings Not Yet Acted On
- **`apply_edit` empty `old_content` guard** — security finding, PR not yet opened. Empty `old_content` bypasses guards; `"" in any_string` is always `True`, allowing arbitrary content prepending to empty files. **High priority.**
- **`execute_parallel` `""` sentinel** — filed as issue #21, PR not yet opened. Return type should be `str | None`. **High priority.**
- **`DEFAULT_MODEL` mismatch** — filed as issue #7 and finding #5 this run. `config.py` uses `"anthropic/claude-sonnet-4-6"` which won't match any `MODEL_OVERRIDES` key (date-suffixed), and `configuration.md` documents yet another name. **Medium priority.**
- **`memory.py` zero test coverage** — `load_working`/`update_working` untested. **Medium priority.**
- **`cli.py` zero test coverage** — `_format_run_context` is a pure function, trivially testable. **Medium priority.**

## Patterns Learned
- Test suite uses real git repos via `tmp_path` — requires explicit git config (`user.email`/`user.name`)
- `"" in any_string` is always `True` — the `apply_edit` empty `old_content` bug is subtle but real
- `MODEL_OVERRIDES` keys use date suffixes; default model name never matches, always falls through to litellm
- No integration tests despite scaffolded directory; unit coverage gaps persist in `memory.py` and `cli.py`
- Rebase failures resolved in recent runs — PR #19 diagnostics appear to be helping

## Next Run Focus
1. **High Priority**: Open PR for `apply_edit` empty `old_content` guard (`sigil/executor.py`)
2. **High Priority**: Open PR for `execute_parallel` `str | None` sentinel fix (`sigil/executor.py`)
3. **Medium Priority**: Sync `DEFAULT_MODEL` across `config.py`, `llm.py` `MODEL_OVERRIDES`, and `configuration.md`
4. **Medium Priority**: Add tests for `memory.py` (`load_working`, `update_working`)
5. **Medium Priority**: Add tests for `cli.py` (`_format_run_context` at minimum)
6. **Low Priority**: Smoke-level tests for `llm.py` and `github.py`

## Notes
- No user rejections recorded
- Self-hosting CI active (PR #17) — Sigil runs on its own repo automatically
- README, LICENSE, PR templates, JSON schema, knowledge diffs, and pre-flight validation all now exist
