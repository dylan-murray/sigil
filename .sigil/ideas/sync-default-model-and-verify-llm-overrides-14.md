---
title: Sync Default Model and Verify LLM Overrides
summary: Update `sigil.core.config.Config` to synchronize the `DEFAULT_MODEL` with
  the documentation (`anthropic/claude-sonnet-4-
status: open
complexity: small
disposition: pr
priority: 5
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Sync Default Model and Verify LLM Overrides

## Description

Update `sigil.core.config.Config` to synchronize the `DEFAULT_MODEL` with the documentation (`anthropic/claude-sonnet-4-6`) and verify that the `MODEL_OVERRIDES` in `sigil.core.llm` are actually functioning. Implementation: 1. Change `DEFAULT_MODEL` in `config.py` to match the docs. 2. Add a unit test in `test_llm.py` that specifically triggers a `MODEL_OVERRIDES` case to ensure the logic isn't dead code. 3. Clean up any discrepancies between the `configuration.md` and the actual code defaults.

## Rationale

Identified as a known bug/inconsistency in `project.md`. Ensuring defaults match documentation is critical for user trust.

