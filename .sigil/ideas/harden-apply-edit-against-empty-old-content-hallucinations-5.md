---
title: Harden apply_edit against empty old_content hallucinations
summary: In `sigil.pipeline.executor.ToolFactory.apply_edit`, implement a check that
  compares the length of `old_content` against
status: open
complexity: small
disposition: pr
priority: 10
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Harden apply_edit against empty old_content hallucinations

## Description

In `sigil.pipeline.executor.ToolFactory.apply_edit`, implement a check that compares the length of `old_content` against the file content. If `old_content` is empty or very short but the agent is trying to replace a large block, flag it as a potential hallucination.

Implementation:
1. Modify the `apply_edit` handler.
2. If `old_content` is not found in the file, instead of just failing, check if the agent is attempting a 'blind write' (replacing everything without context).
3. If the edit seems unsafe (e.g., trying to replace 100 lines with a 5-line snippet without matching context), return a specific error: 'Unsafe edit detected: old_content must match existing code exactly to prevent accidental deletion.'
4. This prevents the common 'hallucinated edit' failure mode.

## Rationale

Hallucinated `old_content` is a leading cause of execution failure. Hardening this tool makes the Engineer agent much more reliable.

