---
title: Cost-Aware Meta-Instruction Learning (Trace Feedback Loop)
summary: Add a `trace_feedback` tool to the `memory` agent. After each run, the agent
  reads `traces/last-run.json` and identifies
status: open
complexity: small
disposition: pr
priority: 13
created: '2026-03-29T16:46:19Z'
---

# Cost-Aware Meta-Instruction Learning (Trace Feedback Loop)

## Description

Add a `trace_feedback` tool to the `memory` agent. After each run, the agent reads `traces/last-run.json` and identifies which agents were most expensive or had the most retries. It then writes a 'Self-Optimization' note in `working.md` (e.g., "The Engineer agent struggled with 'apply_edit' on large files; suggest using smaller chunks"). Implementation: 1. `memory.py` reads the trace file. 2. It summarizes performance bottlenecks. 3. These insights are injected into the system prompts of the relevant agents in the next run. 4. This creates a feedback loop where Sigil learns to be more efficient.

## Rationale

Sigil generates rich trace data, but currently doesn't use it to improve. This feature allows the agent to 'debug' its own performance and adjust its strategy to save tokens and improve success rates.

