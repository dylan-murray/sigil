---
title: Entropy-Based Knowledge Allocation (Priority Compaction)
summary: Implement an 'Information-Theoretic' compaction algorithm in sigil.pipeline.knowledge.
  Instead of just summarizing files
status: open
complexity: medium
disposition: pr
priority: 11
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Entropy-Based Knowledge Allocation (Priority Compaction)

## Description

Implement an 'Information-Theoretic' compaction algorithm in sigil.pipeline.knowledge. Instead of just summarizing files, the Compactor agent should calculate an 'Entropy Score' for knowledge files based on how often they are selected by the Selector agent (tracked in working.md). Files with high selection frequency are expanded with more detail; files rarely used are aggressively compacted or merged. Implementation: 1. Update working.md to track 'knowledge_hits'. 2. Modify compact_knowledge to accept hit-rate data. 3. Update Compactor system prompt to prioritize detail for high-hit files. 4. Add a 'merge_knowledge_files' tool to the Compactor.

## Rationale

Static knowledge compaction eventually hits the 200k char limit. Dynamic allocation ensures the most 'useful' knowledge stays in context while stale info is pruned. Reference: sigil.pipeline.knowledge.compact_knowledge.

