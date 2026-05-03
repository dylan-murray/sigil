---
last_updated: '2026-05-03T16:17:29Z'
manifest_hash: d8b4467a04ebfd4532f578b524306a907c77f6da69f20723411af525510bd3f2
---

## Recent Activity

**Last run:** 2026-04-27  
**Items executed:** 1 succeeded, 0 failed, 0 skipped

### Changes Made
- **Feature: Agent Config Rule Injection into Executor Prompt** (2 retries)  
  Added `{agent_config_section}` placeholder to `EXECUTOR_CONTEXT_PROMPT` in `prompts.py` and `_build_agent_config_section()` in `executor.py`. Displays the engineer agent’s model, max_tokens, max_iterations, and reasoning_effort as a numbered constraints block. Display-only — no execution logic changes.

### PRs Opened (previous run)
- #139–#153: 15 PRs covering security tests/fix, type suppressions removed, sandbox/similarity/attempts tests, generic TypeVar, lambda type fixes, etc.

### Issues Filed
- None

### Failures
- None (all 16 succeeded on first or second attempt)

## Patterns & Insights
- **Display-only changes are low-risk** but may need retries to get prompt formatting right — test with sample output.
- **Type safety fixes are reliable**: mypy suppressions and variable shadowing bugs are consistently fixable in 0–1 retries.
- **Security tests expose real bugs**: Writing tests for security.py found `.aws/credentials` paths were silently not blocked.
- **Generic TypeVar is a force multiplier**: Making `structured_completion` generic fixed errors in knowledge.py, validation.py simultaneously.
- **Lambda default-arg captures are a mypy anti-pattern**: Use nested `def` instead.
- **Compound boolean narrowing doesn't work in mypy**: Inline the guard.
- **Test coverage for pure functions is fast and safe**: sandbox.py, similarity.py, attempts.py all tested with zero runtime dependencies.
- **Variable shadowing across function scope causes mypy confusion**: `result`/`skipped`/`validated` reused with different types.
- **State management features continue to fail**: Avoid proposals requiring persistent cross-session state.
- **80 ideas in backlog**: Prioritize type fixes, test coverage, security hardening.

## Previous Runs (summary)
- Mar 2026 run: 7 PRs (#270-276) — type fixes, dashboard (downgraded to issue), edit hardening
- Apr 2026 run: 15 PRs (#139-153) — security tests/fix, type suppressions removed, sandbox/similarity/attempts tests added

## Next Run Focus
1. Remaining mypy errors in `sigil/core/agent.py` (5 errors around `str | None` model passed to string-only functions)
2. Test coverage gaps: `sigil/pipeline/ideation.py`, `sigil/pipeline/discovery.py` pure functions
3. Type annotations audit on `sigil/integrations/github.py` — likely untyped return values
4. Avoid large architectural proposals; keep PRs under 50 lines changed
5. Check if any `type: ignore` suppressions remain after PRs 145/146 landed
6. Expand agent config injection to parse hard rules from AGENTS.md/CLAUDE.md/.cursorrules files (currently only displays model config)
