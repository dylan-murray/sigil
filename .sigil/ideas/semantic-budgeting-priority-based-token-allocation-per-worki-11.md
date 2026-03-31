---
title: 'Semantic Budgeting: Priority-based Token Allocation per WorkItem'
summary: Implement 'Semantic Budgeting' where the `max_cost_usd` is distributed based
  on the 'Value Density' of an item, rather t
status: open
complexity: medium
disposition: pr
priority: 7
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Semantic Budgeting: Priority-based Token Allocation per WorkItem

## Description

Implement 'Semantic Budgeting' where the `max_cost_usd` is distributed based on the 'Value Density' of an item, rather than a flat cap for the whole run.

Implementation:
1. `sigil/core/llm.py`: Update the budget tracker to accept a `item_id` and `priority`.
2. During `validate_all`, the Triager assigns a 'Budget Allocation' to each approved item (e.g., P1 items get $5.00, P3 items get $0.50).
3. In `executor.py`, if an agent exceeds its specific item budget, it must 'Stop and Justify' via a specific tool call or be terminated.
4. This prevents a single low-priority, 'experimental' idea from consuming 80% of the total run budget due to a coding loop, leaving no room for critical maintenance fixes.

This is a move from 'Run Budget' to 'Unit Economics' for code improvement.

## Rationale

The current `max_cost_usd` is a blunt instrument. A 'runaway' task in the parallel executor can starve other tasks of budget. Semantic budgeting ensures ROI-aligned spending.

