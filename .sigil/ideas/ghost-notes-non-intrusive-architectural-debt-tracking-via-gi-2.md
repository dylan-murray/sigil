---
title: 'Ghost Notes: Non-Intrusive Architectural Debt Tracking via Git Metadata'
summary: Introduce 'Sigil Ghost Mode' using `git notes` to track architectural debt
  without polluting the source code or opening
status: open
complexity: large
disposition: issue
priority: 15
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Ghost Notes: Non-Intrusive Architectural Debt Tracking via Git Metadata

## Description

Introduce 'Sigil Ghost Mode' using `git notes` to track architectural debt without polluting the source code or opening noisy issues.

Implementation:
1. Create a `write_ghost_note` tool for the Auditor.
2. Instead of a GitHub Issue, 'Experimental' or 'Refactoring' findings are attached to specific commits as `git notes` (under a `refs/notes/sigil` namespace).
3. These notes can be pushed to the remote.
4. During future runs, Sigil reads these notes to see if 'debt' is accumulating in specific modules (e.g., 'This file has 3 ghost notes about high complexity').
5. If a file hits a threshold of ghost notes, it gets elevated to a 'Major Refactor' FeatureIdea.
6. This allows Sigil to 'think out loud' about long-term debt without bothering humans until it's actionable.

## Rationale

Maintainers often ignore 'Style' or 'Complexity' issues. Ghost notes provide a non-intrusive way for Sigil to track 'smells' over time until they become critical.

