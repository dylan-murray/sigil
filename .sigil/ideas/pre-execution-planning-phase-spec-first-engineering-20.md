---
title: Pre-Execution Planning Phase (Spec-First Engineering)
summary: Introduce a 'Spec-First' execution mode where the Engineer agent must generate
  a detailed implementation plan (file diff
status: open
complexity: medium
disposition: pr
priority: 12
boldness: balanced
created: '2026-03-31T00:41:14Z'
---

# Pre-Execution Planning Phase (Spec-First Engineering)

## Description

Introduce a 'Spec-First' execution mode where the Engineer agent must generate a detailed implementation plan (file diffs, logic changes, side effects) and have it 'vetted' by an Architect agent *before* any files are modified. Implementation: 1. Add an `Architect` agent to `executor.py`. 2. The Engineer uses a `propose_plan` tool. 3. The Architect reviews the plan and either approves or requests changes. 4. Once approved, the Engineer proceeds to use `apply_edit`. 5. This separates 'thinking' from 'doing' and prevents the Engineer from making messy, partial changes that are hard to roll back.

## Rationale

Directly editing files can lead to 'wandering' implementations. A planning phase ensures the agent has a coherent strategy for the entire task before it starts touching the filesystem.

