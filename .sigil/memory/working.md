---
last_updated: '2026-05-02T15:49:13Z'
manifest_hash: d009d258d31324f821ff532dbc9d566b51916c0b4d84a9312ef851850ea5a8a2
---

## Recent Activity

**Last run:** 2026-04-27  
**Items executed:** 16 succeeded, 0 failed, 0 skipped

### PRs Opened
- #139: Add unit tests for sigil/core/security.py (63 parametrized tests, uncovered path traversal bug)
- #140: Add Config.load edge case tests (13 tests for error paths)
- #141: Convert FileTracker @dataclass to plain class (undeclared attribute mismatch fixed)
- #142: Fix is_sensitive_file path traversal bug — `.aws/credentials` was never matched (critical security fix)
- #143: Remove thin wrapper functions _apply_edit/_create_file, replaced with re-export aliases
- #144: Add parametrized tests for boldness_allowed (21 tests, full rank coverage)
- #145: Fix type:ignore[misc] in llm.py acompletion retry loop
- #146: Remove type:ignore[assignment] in validation.py merge_decisions
- #147: Fix mypy str|None errors in agent.py tool_model paths
- #148: Add edge case tests for similarity module (8 new tests, empty corpus/query/docs)
- #149: Add unit tests for sandbox pure functions (32 tests: _infer_provider, _validate_allowlist, build_network_allowlist)
- #150: Make structured_completion generic (TypeVar[_BM]) — fixes BaseModel attr mypy errors in knowledge.py and validation.py
- #151: Fix mypy type errors in cli.py (variable shadowing: skipped/result, lambda inference)
- #152: Fix lambda type inference mypy errors in executor.py _item_callback
- #153: Fix FileTracker union-attr mypy error in read_file tool (tracker None narrowing through cache_hit bool)

### Changes Made (direct commits)
- Added pre-flight safety validation in executor: blocks binary file edits, whole-file deletions, and excessive line changes. Added `BINARY_EXTENSIONS` set and `is_binary_file()` in `security.py` (duplicated from `discovery.py` to avoid cross-layer dependency). Added `MAX_LINES_PER_EDIT` and `MAX_TOTAL_LINES_CHANGED` constants in `tools.py`.

### Issues Filed
- None

### Failures
- None (all 16 succeeded on first or second attempt)

## Patterns & Insights
- **Type safety fixes are reliable**: mypy suppressions (type:ignore) and variable shadowing bugs are consistently fixable in 0-1 retries.
- **Security tests expose real bugs**: Writing tests for security.py found that `.aws/credentials` paths were silently not blocked. Always test security-critical code.
- **Generic TypeVar is a force multiplier**: Making `structured_completion` generic fixed errors in knowledge.py, validation.py simultaneously.
- **Lambda default-arg captures are a mypy anti-pattern**: `lambda x, _y=y: ...` cannot be typed. Use nested `def` instead.
- **Compound boolean narrowing doesn't work in mypy**: `cache_hit = tracker is not None and ...` followed by `if cache_hit: tracker.method()` still fails. Inline the guard.
- **Test coverage for pure functions is fast and safe**: sandbox.py, similarity.py, attempts.py all tested with zero runtime dependencies — parametrize heavily.
- **Variable shadowing across function scope causes mypy confusion**: `result`/`skipped`/`validated` reused with different types in same function creates cascading errors.
- **State management features continue to fail**: Avoid proposals requiring persistent cross-session state.
- **Pre-flight validation is a good safety net**: Duplicating small constants (like `BINARY_EXTENSIONS`) across layers is acceptable to avoid circular imports or cross-layer coupling.
- **80 ideas in backlog**: Large pool, but many are experimental/speculative. Prioritize type fixes, test coverage, security hardening.

## Previous Runs (summary)
- Mar 2026 run: 7 PRs (#270-276) — type fixes, dashboard (downgraded to issue), edit hardening
- Apr 2026 run (1st): 15 PRs (#139-153) — security tests/fix, type suppressions removed, sandbox/similarity/attempts tests added
- Apr 2026 run (2nd): 1 feature — pre-flight safety validation (security.py, tools.py)

## Next Run Focus
1. Remaining mypy errors in `sigil/core/agent.py` (5 errors around `str | None` model passed to string-only functions — need to narrow or update callers)
2. Test coverage gaps: `sigil/pipeline/ideation.py`, `sigil/pipeline/discovery.py` pure functions
3. Type annotations audit on `sigil/integrations/github.py` — likely untyped return values
4. Add unit tests for new pre-flight safety functions (`is_binary_file`, edit limit constants)
5. Avoid large architectural proposals; keep PRs under 50 lines changed
6. Check if any `type: ignore` suppressions remain after PRs 145/146/147/150/151/152/153
