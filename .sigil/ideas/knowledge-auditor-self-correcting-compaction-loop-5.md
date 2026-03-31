---
title: 'Knowledge Auditor: Self-Correcting Compaction Loop'
summary: Implement a 'Self-Correction' loop in the Knowledge Compactor (`sigil.pipeline.knowledge`).
  After generating a knowledge
status: open
complexity: medium
disposition: issue
priority: 6
boldness: balanced
created: '2026-03-29T18:59:35Z'
---

# Knowledge Auditor: Self-Correcting Compaction Loop

## Description

Implement a 'Self-Correction' loop in the Knowledge Compactor (`sigil.pipeline.knowledge`). After generating a knowledge file, a 'Knowledge Auditor' agent reviews the file against the raw discovery context to ensure no critical architectural details were hallucinated or omitted. Implementation: 1. Add a second pass to `compact_knowledge`. 2. The Auditor agent receives the generated `.md` and the original `discovery_context`. 3. It uses a `suggest_edits` tool to fix inaccuracies. 4. This ensures the 'ground truth' memory Sigil relies on is high-fidelity. 5. This is especially important for the `architecture.md` and `project.md` files.

## Rationale

Sigil's entire pipeline depends on the quality of its knowledge files. A single-pass compaction can miss nuances. A self-correction loop ensures the foundation of Sigil's reasoning is solid.

