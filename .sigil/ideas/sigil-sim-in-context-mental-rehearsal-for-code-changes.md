---
title: 'Sigil-Sim: In-Context Mental Rehearsal for Code Changes'
summary: 'Implement ''Sigil-Sim'': a deterministic injection-based simulation for
  the Executor. Before running code in a real worktr'
status: open
complexity: large
disposition: issue
priority: 6
created: '2026-03-29T16:46:19Z'
---

# Sigil-Sim: In-Context Mental Rehearsal for Code Changes

## Description

Implement 'Sigil-Sim': a deterministic injection-based simulation for the Executor. Before running code in a real worktree, Sigil uses a 'Simulation' tool to generate a 'Predicted Diff' and then asks the QA agent to 'hallucinate' the test output of that diff in a sandbox. If the QA agent predicts a failure in the simulation, the Engineer never even touches the disk. This 'Mental Rehearsal' loop happens entirely in-context, drastically reducing the number of expensive git worktree operations and actual subprocess runs (like pytest) which are slow and prone to environment issues.

## Rationale

Subprocess execution (pytest/ruff) is the slowest part of the pipeline. High-fidelity 'mental models' of code changes can prune 80% of bad implementation paths before they hit the disk.

