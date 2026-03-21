---
last_updated: '2026-03-21T21:04:32Z'
---

# Sigil Working Memory

## Repository Overview
Sigil's own repository — an AI agent for code analysis and improvement. Modern Python structure (pyproject.toml, src layout), type hints throughout, partially implemented test infrastructure. Early-stage but actively improving.

## What Has Been Done

### PRs Opened
- **PR #1**: Fix git config in executor tests (`user.email`/`user.name`) to prevent CI failures
- **PR #2**: Add `.sigil/instructions.md` — human-authored persistent instructions for the agent
- **PR #3**: `sigil status` command to inspect memory, ideas, and pending work
- Additional PRs for `--focus` flag and ignore annotations succeeded (check GitHub for numbers)

### Issues Filed
- **#4**: Integration test directory is empty — no tests for GitHub API, LLM calls, or git worktree ops
- **#5**: `execute_parallel` uses `""` as sentinel for "no branch" — should use `str | None`
- **#6**: `MODEL_OVERRIDES` in `llm.py` may be dead code; no tests for `llm.py`
- **#7**: `DEFAULT_MODEL` in `config.py` doesn't match the model shown in `configuration.md`
- **#8**: GitHub Action example uses `uv tool install sigil` but package isn't published to PyPI
- **#9–#13**: New ideas filed as issues this run (human-in-the-loop approval, cross-agent knowledge sharing, adversarial validation, knowledge file versioning, PR review assistant)

### Attempted This Run (Failed — Rebase Failures)
Three PRs were implemented and committed but failed to rebase onto main:
- `delete_file` tool for executor (dead code removal)
- Semantic diff summaries in working memory
- Per-file ignore rules via `.sigilignore`

These are **downgraded to issues** — the implementations exist in branches but were not merged. Retry with a clean rebase strategy.

## Patterns Learned
- **Rebase failures are recurring** — worktree/rebase onto main is fragile; investigate whether main moved during execution or if there's a branch naming conflict
- Test suite uses real git repos via `tmp_path` — requires explicit git config setup (`user.email`/`user.name`)
- Code/docs drift is present (model name mismatch between `config.py` and `configuration.md`)
- Security-sensitive paths (`apply_edit`, GitHub client) lack defensive guards
- No integration tests exist despite the directory being scaffolded
- `"" in any_string` is always `True` in Python — the `apply_edit` empty `old_content` bug is subtle but real

## Open Issues Not Yet Acted On
- `apply_edit` empty `old_content` guard — validated finding, PR not yet opened (security)
- `execute_parallel` `""` sentinel — validated finding, PR not yet opened (types)
- GitHub token could appear in error logs if invalid/expired (low confidence, security)
- README/LICENSE still missing

## Next Run Focus
1. **High Priority**: Open PR for `apply_edit` empty `old_content` guard (`sigil/executor.py`)
2. **High Priority**: Open PR for `execute_parallel` `str | None` sentinel fix (`sigil/executor.py`)
3. **Medium Priority**: Investigate and fix rebase failures before retrying the three downgraded PRs
4. **Medium Priority**: Sync `DEFAULT_MODEL` between `config.py` and `configuration.md`
5. **Low Priority**: Add smoke-level tests for `llm.py` and `github.py`

## Notes
- No user rejections recorded
- 15 ideas proposed this run; 5 filed as issues, 3 downgraded from failed PRs, rest recorded here
- Rebase failures are now the primary execution reliability concern — prioritize diagnosing root cause
