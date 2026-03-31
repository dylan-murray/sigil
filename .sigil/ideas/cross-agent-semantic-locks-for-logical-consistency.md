---
title: Cross-Agent Semantic Locks for Logical Consistency
summary: Implement 'Cross-Agent Semantic Locks' to prevent race conditions when multiple
  parallel agents try to modify the same l
status: open
complexity: large
disposition: issue
priority: 5
created: '2026-03-29T17:13:30Z'
---

# Cross-Agent Semantic Locks for Logical Consistency

## Description

Implement 'Cross-Agent Semantic Locks' to prevent race conditions when multiple parallel agents try to modify the same logical component (even if they are in different files). For example, if one agent is refactoring a class in `core/` and another is adding a feature that depends on that class in `pipeline/`, they should not run in parallel. Implementation: 1. Add a `_semantic_lock_map` in executor.py. 2. Use the Triager agent to identify 'impacted symbols' for each work item. 3. In `execute_parallel`, use an asyncio.Lock per symbol to ensure exclusive access to logically related code sections.

## Rationale

As Sigil's parallelism increases, file-level isolation (worktrees) isn't enough to prevent logical conflicts. This moves Sigil toward 'Architecture-Aware Concurrency'.

