---
title: 'Semantic Investment: Value-Density Based Resource Allocation'
summary: Implement 'Semantic Budgeting' where the `max_spend_usd` is not just a flat
  cap, but an investment strategy. Introduce a
status: done
complexity: medium
disposition: pr
priority: 3
created: '2026-03-29T16:46:19Z'
---

# Semantic Investment: Value-Density Based Resource Allocation

## Description

Implement 'Semantic Budgeting' where the `max_spend_usd` is not just a flat cap, but an investment strategy. Introduce a `ValueDensity` metric for each WorkItem (calculated by the Triager based on priority, risk, and category). The Agent framework is then configured to dynamically adjust its `max_iterations` and model selection (e.g., upgrading to Opus/GPT-4o for high-density items and sticking to Haiku/Mini for low-density ones) within the same run. This ensures that the most critical $5 of the $20 budget is spent on the most transformative changes, while routine maintenance uses the 'cheapest' successful path.

## Rationale

The current budget is a blunt instrument. As Sigil scales to larger repos, it needs to be smarter about where it 'thinks hard' vs where it 'scripts fast' to stay within user-defined cost limits.

