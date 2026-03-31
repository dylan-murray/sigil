---
title: Budget-Driven Execution Pruning for High-Value Runs
summary: Add a 'Budget-Driven Execution Pruning' strategy in sigil.pipeline.executor.
  Currently, execute_parallel runs items base
status: open
complexity: small
disposition: pr
priority: 1
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Budget-Driven Execution Pruning for High-Value Runs

## Description

Add a 'Budget-Driven Execution Pruning' strategy in sigil.pipeline.executor. Currently, execute_parallel runs items based on priority. This idea adds a 'Cost-to-Value' score. If a run's `max_cost_usd` is 50% depleted, the pipeline automatically skips 'Large' complexity ideas or 'Low' risk findings to ensure the remaining budget is reserved for 'High' risk/priority items. Implementation: 1. In `execute_parallel`, check `get_usage().cost_usd`. 2. Calculate `remaining_ratio`. 3. Filter `items` list if `remaining_ratio < 0.5` based on `item.priority` and `item.complexity`.

## Rationale

Sigil can hit its budget cap while working on low-value style fixes, leaving high-priority security or bug fixes unaddressed. This ensures intelligent resource allocation during long runs.

