---
title: Budget-Driven Execution Pruning for High-Value Runs
summary: Implement 'Budget-Driven Execution Pruning' in `sigil.pipeline.executor`.
  Currently, `execute_parallel` runs items based
status: open
complexity: small
disposition: pr
priority: 4
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Budget-Driven Execution Pruning for High-Value Runs

## Description

Implement 'Budget-Driven Execution Pruning' in `sigil.pipeline.executor`. Currently, `execute_parallel` runs items based on priority until the list is empty or the global budget is hit. This can lead to starting a high-priority task but running out of money halfway through. Implementation: 1. Before starting any execution, estimate the cost of the remaining items based on their `priority` and `complexity`. 2. If the estimated cost exceeds the remaining `max_cost_usd`, prune the lowest-priority items from the run immediately. 3. This ensures that the budget is 'reserved' for the most important fixes and we don't waste money on low-value items only to fail the high-value ones later.

## Rationale

As Sigil scales to more complex tasks, budget management becomes a strategic problem, not just a safety check. We should spend our dollars on the most impactful PRs first.

