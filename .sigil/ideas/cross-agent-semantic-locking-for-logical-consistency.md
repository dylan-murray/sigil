---
title: Cross-Agent Semantic Locking for Logical Consistency
summary: Implement 'Cross-Agent Semantic Locking' to enable safe, logical parallelism
  when multiple agents are modifying the same
status: open
complexity: medium
disposition: pr
priority: 5
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Cross-Agent Semantic Locking for Logical Consistency

## Description

Implement 'Cross-Agent Semantic Locking' to enable safe, logical parallelism when multiple agents are modifying the same codebase.

Implementation:
1. In `sigil.pipeline.executor.execute_parallel`, create a `SemanticLockManager`.
2. When an agent starts working on a finding, it 'locks' not just the file, but the 'Function/Class Symbols' it intends to touch (extracted from the `implementation_spec`).
3. If a second agent's task overlaps with these symbols, it is queued or diverted to a different task.
4. This prevent race conditions where two agents refactor the same logic in different worktrees, leading to unresolvable rebase conflicts.

This elevates parallelism from simple 'file-level' locking to 'logic-level' coordination.

## Rationale

Current parallelism is file-blind until rebase. Semantic locks allow for higher concurrency with lower conflict rates.

