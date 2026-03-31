---
title: Semantic Fingerprinting for Advanced PR/Issue Deduplication
summary: Implement a 'Semantic Diff Analysis' tool for the `integrations/github` module
  to improve deduplication. Instead of simp
status: open
complexity: medium
disposition: pr
priority: 5
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Semantic Fingerprinting for Advanced PR/Issue Deduplication

## Description

Implement a 'Semantic Diff Analysis' tool for the `integrations/github` module to improve deduplication. Instead of simple string matching or Jaccard similarity on titles/bodies, use a small LLM call to compare the 'Intent' of a new finding against existing open PRs/issues. Implementation: 1. Add `_is_semantically_equivalent(item, existing_issue)` helper. 2. This helper sends the description of both to a fast model (Haiku) to ask "Are these describing the same underlying root cause?". 3. Integrate this into `dedup_items`. 4. This catches cases where a finding is described differently but targets the same bug, preventing duplicate PR spam.

## Rationale

Duplicate PRs are a major friction point for autonomous agents. Semantic deduplication is much more robust than keyword matching, especially when different models describe the same problem in different ways.

