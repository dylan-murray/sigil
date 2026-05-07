---
last_updated: '2026-05-01T23:19:42Z'
manifest_hash: c1c08c3e533292a8748b5659d8a2680481f14ef6fb73a109fca3e44f357e4eca
---

## Recent Activity

**Last run:** 2026-04-27  
**Items executed:** 1 succeeded, 0 failed, 0 skipped

### PRs Opened
- #154: Implement closed issue deduplication to respect "won't fix" decisions — `dedup_items()` now checks closed issues with `WONTFIX_LABELS` (e.g., "wontfix", "not planned") and a 90-day lookback, using a stricter similarity threshold (0.8) to avoid re-proposing rejected ideas.

### Issues Filed
- None

### Failures
- None (1 succeeded on second attempt – first attempt had off-by-one in lookback date calculation)

## Patterns & Insights
- **Closed issue deduplication is delicate**: The first attempt used `datetime.now() - timedelta(days=90)` but compared against `issue.closed_at` which is timezone-aware; fixed by using `datetime.now(timezone.utc)`. Always handle timezone-aware datetimes when querying GitHub API.
- **Won't-fix labels are a reliable signal**: Using a frozenset of common labels (`wontfix`, `not planned`, `invalid`, `duplicate`) catches most cases. Custom labels can be added via config.
- **Type safety fixes remain reliable**: mypy suppressions and variable shadowing bugs are consistently fixable in 0-1 retries.
- **Security tests expose real bugs**: Writing tests for security.py found that `.aws/credentials` paths were silently not blocked. Always test security-critical code.
- **Generic TypeVar is a force multiplier**: Making `structured_completion` generic fixed errors in knowledge.py, validation.py simultaneously.
- **Lambda default-arg captures are a mypy anti-pattern**: Use nested `def` instead.
- **Compound boolean narrowing doesn't work in mypy**: Inline the guard.
- **Test coverage for pure functions is fast and safe**: sandbox.py, similarity.py, attempts.py all tested with zero runtime dependencies.
- **Variable shadowing across function scope causes mypy confusion**: Avoid reusing names like `result`/`skipped` with different types.
- **State management features continue to fail**: Avoid proposals requiring persistent cross-session state.
- **80 ideas in backlog**: Prioritize type fixes, test coverage, security hardening.

## Previous Runs (summary)
- Mar 2026 run: 7 PRs (#270-276) — type fixes, dashboard (downgraded to issue), edit hardening
- Apr 2026 run: 16 PRs (#139-154) — security tests/fix, type suppressions removed, sandbox/similarity/attempts tests, closed issue deduplication

## Next Run Focus
1. Remaining mypy errors in `sigil/core/agent.py` (5 errors around `str | None` model passed to string-only functions)
2. Test coverage gaps: `sigil/pipeline/ideation.py`, `sigil/pipeline/discovery.py` pure functions
3. Type annotations audit on `sigil/integrations/github.py` — likely untyped return values (check after #154)
4. Verify closed issue deduplication works end-to-end with a test for the new `dedup_items` logic
5. Avoid large architectural proposals; keep PRs under 50 lines changed
6. Check if any `type: ignore` suppressions remain after PRs 145/146 landed
