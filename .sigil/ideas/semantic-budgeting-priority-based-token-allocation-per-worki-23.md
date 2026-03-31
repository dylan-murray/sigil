---
title: 'Semantic Budgeting: Priority-based Token Allocation per WorkItem'
summary: Implement 'Semantic Budgeting' in `sigil.core.llm` and the `Agent` framework.
  Instead of a flat `max_spend_usd` for the
status: open
complexity: medium
disposition: pr
priority: 4
boldness: balanced
created: '2026-03-31T00:41:14Z'
---

# Semantic Budgeting: Priority-based Token Allocation per WorkItem

## Description

Implement 'Semantic Budgeting' in `sigil.core.llm` and the `Agent` framework. Instead of a flat `max_spend_usd` for the whole run, allow the Triager/Validator to assign a 'Token Bounty' to each approved WorkItem based on its priority and complexity. High-priority architectural fixes get a larger bounty; small doc fixes get a tiny one. Implementation: 1. Update `Finding` and `FeatureIdea` to include a `token_bounty_usd` field. 2. The Triager sets this during validation. 3. The `Agent` loop in `executor.py` monitors its specific spend against the item's bounty and self-terminates or switches to a cheaper model if the bounty is nearly exhausted. 4. This prevents a single low-value item from consuming the entire run's budget.

## Rationale

Sigil currently treats all tasks as equal in cost. Semantic budgeting ensures that expensive, high-quality models are reserved for high-value tasks, while low-value tasks are strictly capped.

