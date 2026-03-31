---
title: Cross-Agent Semantic Locking for Logical Consistency in Parallel Runs
summary: Implement 'Cross-Agent Semantic Locking' in `sigil.pipeline.executor.execute_parallel`.
  When multiple agents are running
status: open
complexity: medium
disposition: issue
priority: 4
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Cross-Agent Semantic Locking for Logical Consistency in Parallel Runs

## Description

Implement 'Cross-Agent Semantic Locking' in `sigil.pipeline.executor.execute_parallel`. When multiple agents are running in different worktrees, they currently have no way of knowing if they are modifying the same logical component (e.g., two agents both adding fields to `Config.py`). Create a `LockManager` in `sigil.core.utils` that agents use to acquire 'Semantic Locks' based on file paths or class names. If Agent B tries to modify a file that Agent A is already working on, Agent B is paused or its task is rescheduled. This prevents 'Logical Merge Conflicts' where code is syntactically correct (git rebase works) but architecturally broken.

## Rationale

Rebase-only conflict resolution is insufficient for semantic changes. Logic locks ensure parallel agents don't 'step on each other's toes' conceptually.

