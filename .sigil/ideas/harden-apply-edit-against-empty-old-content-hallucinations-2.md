---
title: Harden apply_edit against empty old_content hallucinations
summary: In `sigil.pipeline.executor.ToolFactory.apply_edit`, implement a check that
  compares the length of `old_content` against
status: open
complexity: small
disposition: pr
priority: 6
created: '2026-03-29T16:46:19Z'
---

# Harden apply_edit against empty old_content hallucinations

## Description

In `sigil.pipeline.executor.ToolFactory.apply_edit`, implement a check that compares the length of `old_content` against the total file length. If `old_content` is empty or matches a significant percentage of the file without specific line markers, require the LLM to provide more context or use a `replace_file` tool instead. This prevents accidental full-file wipes when the LLM hallucinates an empty 'old' block.

## Rationale

Identified as a 'Known Bug' in `project.md`. Protects against catastrophic file overwrites.

