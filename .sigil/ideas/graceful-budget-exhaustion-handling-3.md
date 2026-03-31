---
title: Graceful Budget Exhaustion Handling
summary: Add a `cost_limit_reached` flag to the `AgentResult` and `PipelineContext`.
  In `sigil.cli._run`, if a stage (like `analy
status: open
complexity: medium
disposition: pr
priority: 3
created: '2026-03-29T17:13:30Z'
---

# Graceful Budget Exhaustion Handling

## Description

Add a `cost_limit_reached` flag to the `AgentResult` and `PipelineContext`. In `sigil.cli._run`, if a stage (like `analyze`) consumes enough budget that the remaining stages (execution) are likely to fail, Sigil should 'Gracefully Degrade' by skipping lower-priority items or switching to a much cheaper model for the remaining tasks. Implementation: 1. Monitor budget in `_run` loop. 2. If > 70% of `max_spend_usd` is gone before execution starts, trigger 'Economy Mode'. 3. Economy Mode forces all agents to use the `fast_model` (Haiku) and reduces `max_parallel_tasks` to 1. 4. This ensures the run finishes and publishes *something* rather than just crashing.

## Rationale

Hard budget crashes are frustrating because they leave the repo in an uncertain state with no results. Graceful degradation ensures that even on a tight budget, the most important work gets finished.

