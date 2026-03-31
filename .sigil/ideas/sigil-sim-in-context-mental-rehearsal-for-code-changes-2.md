---
title: 'Sigil-Sim: In-Context Mental Rehearsal for Code Changes'
summary: "Implement 'Sigil-Sim'\u2014a deterministic, in-context simulation environment\
  \ for the Executor. Before running code in a real"
status: open
complexity: large
disposition: issue
priority: 4
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Sigil-Sim: In-Context Mental Rehearsal for Code Changes

## Description

Implement 'Sigil-Sim'—a deterministic, in-context simulation environment for the Executor. Before running code in a real worktree, the Executor performs a 'Mental Rehearsal'.

Implementation:
1. Add a `rehearse_changes` tool to the Engineer agent in `sigil.pipeline.executor`.
2. This tool takes a proposed diff and simulates the output of `pre_hooks` and `post_hooks` by calling a separate 'Sim-Agent' that predicts how `pytest` or `ruff` would react to that specific diff.
3. The Engineer iterates in this 'Mental Sandbox' before ever touching the disk.
4. Only once the Sim-Agent predicts a 'Pass' does the Engineer call `apply_edit` for real.

This drastically reduces the cost of failed worktree executions and limit-exceeding retries by catching obvious logical errors in-memory.

## Rationale

Disk I/O and worktree setup are the most expensive parts of the pipeline. In-context rehearsal saves significant time and compute.

