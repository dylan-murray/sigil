---
title: 'Semantic Budgeting: Priority-based Token Allocation per WorkItem'
summary: Implement 'Semantic Budgeting' in `sigil.core.llm`. Instead of a flat `max_spend_usd`
  for the whole run, allow the Triag
status: open
complexity: medium
disposition: pr
priority: 5
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Semantic Budgeting: Priority-based Token Allocation per WorkItem

## Description

Implement 'Semantic Budgeting' in `sigil.core.llm`. Instead of a flat `max_spend_usd` for the whole run, allow the Triager to allocate 'Token Credits' to specific WorkItems based on their priority. A Priority 1 bug fix might get $2.00 of budget, while a Priority 5 refactor gets $0.10. If an agent exceeds its specific allocation, it must 'ask' the Triager for more (a handoff) or terminate. This ensures that expensive models (Opus/GPT-4) are spent on high-value problems while low-value tasks are either handled by cheap models or cut short.

## Rationale

Currently, a single complex but low-value refactor can eat the entire run budget. Semantic budgeting aligns financial cost with architectural value.

