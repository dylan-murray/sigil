---
last_updated: '2026-03-22T22:50:30Z'
---

# Sigil Working Memory

## Repository Overview
Sigil's own repository — an AI agent for code analysis and improvement. Modern Python structure (pyproject.toml, src layout), type hints throughout, partially implemented test infrastructure. Early-stage but actively improving. Self-hosting CI active.

## What Has Been Done

### PRs Opened
- **#1–#3**: Git config fix, instructions.md, `sigil status` command
- **#16–#20**: Ignore config globs, CI self-hosting, knowledge selection caching, rebase diagnostics, README/LICENSE
- **#27–#30**: Pre-flight validation, knowledge diff annotations, JSON schema export, PR template customization
- **#36–#38**: Commit message archaeology, config profiles, knowledge file health metrics
- **#44**: Knowledge File Pinning — mark files as always-load for critical context
- **#50**: Sigil REPL — interactive `sigil ask` command for codebase Q&A
- **#51**: Temporal Regression Analysis — detect when code quality degraded and surface culprit commit

### Issues Filed
- **#4–#13**: Integration test gaps, `execute_parallel` sentinel, dead code, model mismatch, GitHub Action, human-in-the-loop, cross-agent knowledge, adversarial validation, versioning, PR review
- **#21–#25**: `execute_parallel` sentinel (confirmed), `memory.py` coverage, `cli.py` coverage, counterfactual refactoring, path-scoped runs
- **#31–#35**: Won't-Fix registry, execution agent specialization, run history log, knowledge quality validation, dependency-aware work item ordering
- **#39–#43**: Diff-level validation, PR comment mining, finding confidence scores, idea genealogy, execution sandbox mode
- **#45–#49**: Executor retry learning, apply edit fuzzy matching, pre/post run hooks, finding deduplication fingerprints, Sigil audit trail
- **#52–#56**: Draft PR Mode, PR Size Guard, Target Branch Configuration, CODEOWNERS-aware assignment, finding synthesis
- **#57–#61**: Probabilistic execution routing, finding persistence tracker, PR style mirroring, Sigil shadow mode, streaming pipeline progress (this run)

## Open Validated Findings Not Yet Acted On
- **`apply_edit` empty `old_content` guard** — `"" in any_string` is always `True`; allows arbitrary content prepending. **High priority — PR not yet opened.**
- **Regression test for `apply_edit` empty guard** — `tests/unit/test_executor.py` needs test verifying `_apply_edit(repo, "file.py", "", "injected")` is rejected. Bundle with fix PR.
- **`execute_parallel` `""` sentinel** — filed as #21; return type should be `str | None`. **High priority — PR not yet opened.**
- **`DEFAULT_MODEL` mismatch** — `config.py` model name never matches `MODEL_OVERRIDES` keys (date-suffixed). **Medium priority.**
- **`memory.py` zero test coverage** — `load_working`/`update_working` untested. **Medium priority.**
- **`cli.py` zero test coverage** — `_format_run_context` is a pure function, trivially testable. **Medium priority.**

## Patterns Learned
- Test suite uses real git repos via `tmp_path` — requires explicit git config (`user.email`/`user.name`)
- `"" in any_string` is always `True` — the `apply_edit` empty `old_content` bug is subtle but real
- `MODEL_OVERRIDES` keys use date suffixes; default model name never matches, always falls through to litellm
- No integration tests despite scaffolded directory; unit coverage gaps persist in `memory.py` and `cli.py`
- **Execution failure pattern**: Config/infrastructure-touching PRs consistently fail (Draft PR Mode, PR Size Guard, Target Branch Config, Config Schema Migration, Per-File Boldness, Validate-Config, Counterfactual Logging all downgraded). Bug fixes and new commands succeed more reliably.
- Findings #2 and #4 (apply_edit bug + regression test) were re-validated this run — these are persistent, real bugs that keep surfacing.

## Next Run Focus
1. **High Priority**: Open PR for `apply_edit` empty `old_content` guard + regression test (`sigil/executor.py` + `tests/unit/test_executor.py`) — bundle fix and test together. This has been validated twice; execute it.
2. **High Priority**: Open PR for `execute_parallel` `str | None` sentinel fix (`sigil/executor.py`)
3. **Medium Priority**: Sync `DEFAULT_MODEL` across `config.py`, `llm.py` `MODEL_OVERRIDES`, and `configuration.md`
4. **Medium Priority**: Add tests for `memory.py` (`load_working`, `update_working`)
5. **Medium Priority**: Add tests for `cli.py` (`_format_run_context` at minimum)

## Notes
- No user rejections recorded across all runs
- Self-hosting CI active (PR #17) — Sigil runs on its own repo automatically
- Feature surface: README, LICENSE, PR templates, JSON schema, knowledge diffs, pre-flight validation, config profiles, knowledge health metrics, commit archaeology, knowledge file pinning, REPL, temporal regression analysis
