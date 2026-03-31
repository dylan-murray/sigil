---
title: Refactor executor branch sentinel to Optional[str]
summary: Update `sigil.pipeline.executor.execute_parallel` and its return type hints
  to use `str | None` for branch names instead
status: open
complexity: small
disposition: pr
priority: 9
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Refactor executor branch sentinel to Optional[str]

## Description

Update `sigil.pipeline.executor.execute_parallel` and its return type hints to use `str | None` for branch names instead of the empty string `""` sentinel.

Implementation:
1. Change the return type of `execute_parallel` and `_execute_in_worktree` to `tuple[WorkItem, ExecutionResult, str | None]`.
2. Update `publish_results` to handle `None` as 'no branch created'.
3. This is a clean-up of a known 'smell' identified in the project's working memory.

## Rationale

Using empty strings as sentinels for optional data is a Python anti-pattern. Moving to `Optional[str]` (or `str | None`) improves type safety and clarity.

