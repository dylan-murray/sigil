---
title: Semantic Fingerprinting for Advanced PR/Issue Deduplication
summary: Implement a 'Semantic Diff Analysis' tool for the `integrations/github` module
  to improve deduplication. Instead of simp
status: open
complexity: medium
disposition: pr
priority: 6
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Semantic Fingerprinting for Advanced PR/Issue Deduplication

## Description

Implement a 'Semantic Diff Analysis' tool for the `integrations/github` module to improve deduplication. Instead of simple string matching or Jaccard similarity on titles, use a small LLM pass to compare a new finding/idea against existing open issues. Implementation: 1. In `dedup_items`, for any item that isn't an exact match, collect the top 5 'similar' existing issues. 2. Pass the new item and the 5 candidates to a 'DedupAgent'. 3. The agent returns a boolean: 'Is this the same logical change?'. 4. This catches cases where titles differ but the underlying fix (e.g., 'fix race condition in mcp.py' vs 'harden mcp connection logic') is identical.

## Rationale

Duplicate PRs/Issues are a major friction point. Titles are often hallucinated or varied by LLMs. Semantic deduplication ensures Sigil doesn't spam the repo with logically identical proposals just because the wording changed.

