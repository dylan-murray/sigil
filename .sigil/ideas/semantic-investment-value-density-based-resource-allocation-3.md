---
title: 'Semantic Investment: Value-Density Based Resource Allocation'
summary: Implement 'Semantic Budgeting' where the `max_spend_usd` is distributed based
  on the 'Value Density' of an item, rather
status: open
complexity: medium
disposition: pr
priority: 4
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Semantic Investment: Value-Density Based Resource Allocation

## Description

Implement 'Semantic Budgeting' where the `max_spend_usd` is distributed based on the 'Value Density' of an item, rather than a flat cap.

Implementation:
1. In `sigil.pipeline.validation`, the Triager/Arbiter assigns a `budget_weight` (0.1 to 2.0) to each approved item based on its priority and risk.
2. The `execute_parallel` function calculates a `per_item_cap = (remaining_budget / remaining_items) * budget_weight`.
3. The `Agent` framework in `sigil.core.agent` is updated to accept a `session_budget`.
4. If an individual execution exceeds its allocated 'Semantic Budget', it is aborted early, even if the total run budget hasn't been hit.
5. This ensures we don't spend $15 on a low-priority 'unused import' fix while leaving $5 for a critical security patch.

## Rationale

Currently, a single 'runaway' low-value task can consume the entire run budget. Semantic budgeting ensures resource allocation aligns with the perceived value of the improvement.

