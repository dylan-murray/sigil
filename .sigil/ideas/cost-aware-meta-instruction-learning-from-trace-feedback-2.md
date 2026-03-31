---
title: Cost-Aware Meta-Instruction Learning from Trace Feedback
summary: 'Introduce ''Sigil Self-Optimization'' (SSO) by adding a `trace_feedback`
  tool to the `memory` agent.   Implementation: 1.'
status: open
complexity: small
disposition: pr
priority: 7
boldness: experimental
created: '2026-03-31T00:14:08Z'
---

# Cost-Aware Meta-Instruction Learning from Trace Feedback

## Description

Introduce 'Sigil Self-Optimization' (SSO) by adding a `trace_feedback` tool to the `memory` agent. 

Implementation:
1. After each run, the `memory` agent reads `.sigil/traces/last-run.json`.
2. It identifies the most expensive agents and those with the most retries/doom loops.
3. It generates a 'Performance Meta-Instruction' for the next run (e.g., "The Engineer agent is struggling with `imports`—be more explicit about absolute paths").
4. This meta-instruction is stored in `working.md` and injected into the system prompt of the relevant agent in future runs.

This creates a closed-loop system where Sigil learns from its own execution failures and cost inefficiencies.

## Rationale

Sigil generates rich trace data but doesn't currently use it to improve its own behavior. This turns traces into a learning signal.

