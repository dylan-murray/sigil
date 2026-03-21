---
last_updated: '2026-03-21T18:25:20Z'
---

# Sigil Working Memory

## Repository Overview
Sigil's own repository — an AI agent for code analysis and improvement. Modern Python structure (pyproject.toml, src layout), type hints throughout, partially implemented test infrastructure. Early-stage but actively improving.

## What Has Been Done

### PRs Opened
- **PR #1**: Fix git config in executor tests (`user.email`/`user.name`) to prevent CI failures
- **PR #2**: Add `.sigil/instructions.md` — human-authored persistent instructions for the agent
- **PR #3**: `sigil status` command to inspect memory, ideas, and pending work
- (PRs for `--focus` flag and ignore annotations also succeeded — check GitHub for numbers)

### Issues Filed
- **#4**: Integration test directory is empty — no tests for GitHub API, LLM calls, or git worktree ops
- **#5**: `execute_parallel` uses empty string `""` as sentinel for "no branch" — should use `str | None`
- **#6**: `MODEL_OVERRIDES` in `llm.py` may be dead code; no tests for `llm.py`
- **#7**: `DEFAULT_MODEL` in `config.py` doesn't match the model shown in `configuration.md`
- **#8**: GitHub Action example uses `uv tool install sigil` but package isn't published to PyPI

## Open Issues Not Yet Acted On
- `apply_edit` tool has no guard against empty `old_content` — potential unintended file replacement (security)
- GitHub token could potentially appear in error logs if invalid/expired (security, low confidence)

## Patterns Learned
- Test suite uses real git repos via `tmp_path` — fragile without explicit git config setup
- Code/docs drift is present (model name mismatch between `config.py` and `configuration.md`)
- Security-sensitive paths (`apply_edit`, GitHub client) lack defensive guards
- No integration tests exist despite the directory being scaffolded

## Ideas Proposed (Not Yet Implemented)
- PR Outcome Learning: harvest merged/closed PR signals to tune behavior
- LLM Cost Estimation: pre-run token budget report and `--budget` flag
- `sigil teach`: inject domain knowledge directly into memory
- Execution Trace Export: save LLM tool-call transcripts for debugging
- Execution Diff Preview: show proposed changes before committing to GitHub
- Knowledge Correction Annotations: let humans flag wrong/outdated knowledge files
- Structured Run Logs: JSON/JSONL output for CI integration

## Next Run Focus
1. **High Priority**: Fix `apply_edit` empty `old_content` guard (security, executor.py)
2. **High Priority**: Fix `execute_parallel` return type — replace `""` sentinel with `str | None`
3. **Medium Priority**: Add at least smoke-level tests for `llm.py` and `github.py`
4. **Medium Priority**: Sync `DEFAULT_MODEL` between `config.py` and `configuration.md`
5. **Low Priority**: Pick up one of the unimplemented ideas above (cost estimation or diff preview are high value)

## Notes
- No user rejections recorded yet
- Documentation PRs from Run 1 were planned but superseded by more targeted fixes in Run 2
- README/LICENSE still missing — worth revisiting if no higher-priority work exists
