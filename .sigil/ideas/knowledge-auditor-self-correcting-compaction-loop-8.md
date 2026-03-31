---
title: 'Knowledge Auditor: Self-Correcting Compaction Loop'
summary: Implement a 'Self-Correction' loop in the Knowledge Compactor (`sigil.pipeline.knowledge`).
  After generating a knowledge
status: open
complexity: medium
disposition: pr
priority: 5
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Knowledge Auditor: Self-Correcting Compaction Loop

## Description

Implement a 'Self-Correction' loop in the Knowledge Compactor (`sigil.pipeline.knowledge`). After generating a knowledge file, a separate 'Auditor' pass verifies the file against the source code it claims to summarize.

Implementation:
1. After `compact_knowledge` produces a set of `.md` files, trigger a `validate_knowledge` agent.
2. This agent is given one knowledge file and the `discovery_context`.
3. It must check for: 1) Hallucinated file paths, 2) Outdated descriptions (e.g., mentions a class that was deleted), 3) Missing critical components.
4. If errors are found, it uses the `INCREMENTAL` compaction logic to fix the specific file.
5. This ensures the 'source of truth' for all other agents (the knowledge base) is actually accurate.

## Rationale

All Sigil agents rely on the `.sigil/memory/` files. If the compactor hallucinates or misses a major architectural change, every subsequent agent (Auditor, Engineer) will operate on false premises.

