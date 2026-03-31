---
title: Cost-Aware Meta-Instruction Learning (Trace Feedback Loop)
summary: Introduce 'Sigil Self-Optimization' (SSO) by adding a `trace_feedback` tool
  to the `memory` agent. After each run, the a
status: done
complexity: small
disposition: pr
priority: 3
created: '2026-03-29T18:16:01Z'
---

# Cost-Aware Meta-Instruction Learning (Trace Feedback Loop)

## Description

Introduce 'Sigil Self-Optimization' (SSO) by adding a `trace_feedback` tool to the `memory` agent. After each run, the agent reads `traces/last-run.json` to identify which agents had the highest 'Retry Rate' or 'Token Waste' (e.g., Engineer spent $5 on a small fix). It then writes 'Efficiency Directives' to `working.md` (e.g., 'When editing sigil/core/llm, use more targeted read_file calls to save tokens'). These directives are injected into future prompts as 'Meta-Instructions', allowing Sigil to learn the most cost-effective way to interact with its specific host repository over time.

## Rationale

Sigil generates rich trace data in `traces/last-run.json` but doesn't close the loop. This feature makes the agent self-aware of its own operational costs and efficiency.

