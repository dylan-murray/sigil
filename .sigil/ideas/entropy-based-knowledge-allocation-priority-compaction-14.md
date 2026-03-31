---
title: Entropy-Based Knowledge Allocation (Priority Compaction)
summary: Implement an 'Information-Theoretic' compaction algorithm in `sigil.pipeline.knowledge`.
  Instead of just summarizing fil
status: open
complexity: medium
disposition: pr
priority: 10
boldness: balanced
created: '2026-03-31T00:41:14Z'
---

# Entropy-Based Knowledge Allocation (Priority Compaction)

## Description

Implement an 'Information-Theoretic' compaction algorithm in `sigil.pipeline.knowledge`. Instead of just summarizing files, the Compactor should identify 'High-Entropy' areas of the codebase (frequently changing code, complex logic, or missing docs) and allocate more knowledge budget to them, while 'Low-Entropy' areas (boilerplate, stable utils) are aggressively compressed into one-liners. This ensures the 200k char knowledge budget is spent where it provides the most 'Surprise' or utility to the agents, rather than being distributed evenly by file size. Change `compact_knowledge` to calculate a 'Density Score' for repo areas based on git log frequency and cyclomatic complexity.

## Rationale

The current knowledge budget is linear. In large repos, Sigil loses nuance in complex areas because it treats a 1000-line constant file the same as a 1000-line core logic file. Reference: `pipeline/knowledge.py` budget logic.

