---
title: Cost-Aware Meta-Instruction Learning (Trace Feedback Loop)
summary: Introduce 'Sigil Self-Optimization' (SSO) by adding a `trace_feedback` tool
  to the `memory` agent. After each run, the a
status: open
complexity: small
disposition: issue
priority: 5
created: '2026-03-29T17:47:08Z'
---

# Cost-Aware Meta-Instruction Learning (Trace Feedback Loop)

## Description

Introduce 'Sigil Self-Optimization' (SSO) by adding a `trace_feedback` tool to the `memory` agent. After each run, the agent reads `traces/last-run.json` and identifies which agents were most expensive or had the most retries.

Implementation:
1. Update `sigil.state.memory.update_working` to also receive the path to `last-run.json`.
2. The `memory` agent (Haiku) analyzes the trace summary.
3. It writes a 'Performance Note' into `working.md` (e.g., "Engineer agent struggled with test_executor.py, 4 retries").
4. In subsequent runs, this note is injected into the `Engineer` agent's prompt as a 'Lesson Learned'.

This creates a closed-loop system where Sigil becomes more efficient over time by observing its own failures and costs.

## Rationale

We have the data in `traces/`, but we don't use it. This feature turns the 'Trace' functionality into a 'Learning' functionality, directly supporting the 'Persistent Memory' principle in architecture.md.

