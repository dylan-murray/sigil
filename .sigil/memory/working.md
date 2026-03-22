---
last_updated: '2026-03-21T22:24:02Z'
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
- **PR #20**: README and LICENSE — missing project documentation

### Issues Filed
- **#4**: Integration test directory empty
- **#5**: `execute_parallel` uses `""` sentinel — should be `str | None`
- **#6**: `MODEL_OVERRIDES` may be dead code; no tests for `llm.py`
- **#7**: `DEFAULT_MODEL` mismatch between `config.py` and `configuration.md`
- **#8**: GitHub Action example references unpublished PyPI package
- **#9–#13**: Human-in-the-loop approval, cross-agent knowledge sharing, adversarial validation, knowledge file versioning, PR review assistant
- **#21**: `execute_parallel` `""` sentinel type fix (confirmed finding)
- **#22**: `memory.py` has zero test coverage — `load_working`/`update_working` untested
- **#23**: `cli.py` has zero test coverage — `_format_run_context` and pipeline untested
- **#24–#25**: Additional ideas filed (counterfactual refactoring, path-scoped runs, etc.)

## Patterns Learned
- Rebase failures were recurring but PR #19 adds diagnostics — monitor whether this resolves the issue
- Test suite uses real git repos via `tmp_path` — requires explicit git config (`user.email`/`user.name`)
- Code/docs drift present: model name mismatch between `config.py` and `configuration.md`
- `"" in any_string` is always `True` — the `apply_edit` empty `old_content` bug is subtle but real
- No integration tests despite scaffolded directory; unit test coverage gaps in `memory.py` and `cli.py`

## Open Validated Findings Not Yet Acted On
- **`apply_edit` empty `old_content` guard** — security finding, PR not yet opened. Empty `old_content` bypasses guards and allows arbitrary content prepending. High priority.
- **`execute_parallel` `""` sentinel** — filed as issue #21, PR not yet opened
- **`DEFAULT_MODEL` mismatch** — filed as issue #7, PR not yet opened

## Next Run Focus
1. **High Priority**: Open PR for `apply_edit` empty `old_content` guard (`sigil/executor.py`)
2. **High Priority**: Open PR for `execute_parallel` `str | None` sentinel fix (`sigil/executor.py`)
3. **Medium Priority**: Sync `DEFAULT_MODEL` between `config.py` and `configuration.md`
4. **Medium Priority**: Add tests for `memory.py` (`load_working`, `update_working`)
5. **Medium Priority**: Add tests for `cli.py` (`_format_run_context` at minimum — pure function, easy to test)
6. **Low Priority**: Add smoke-level tests for `llm.py` and `github.py`

## Notes
- No user rejections recorded
- Rebase failures resolved this run (0 failures, 1 retry succeeded) — diagnostics PR #19 may help long-term
- README and LICENSE now exist (PR #20)
- Self-hosting CI added (PR #17) — Sigil will now run on its own repo automatically
