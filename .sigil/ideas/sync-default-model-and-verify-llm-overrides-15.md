---
title: Sync Default Model and Verify LLM Overrides
summary: Update `sigil.core.config.Config` to synchronize the `DEFAULT_MODEL` with
  the documentation (`anthropic/claude-sonnet-4-
status: open
complexity: small
disposition: pr
priority: 8
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Sync Default Model and Verify LLM Overrides

## Description

Update `sigil.core.config.Config` to synchronize the `DEFAULT_MODEL` with the documentation (`anthropic/claude-sonnet-4-6`) and add a validation test for `MODEL_OVERRIDES` in `llm.py`.

Implementation:
1. Change `DEFAULT_MODEL` in `sigil/core/config.py` to match `configuration.md`.
2. Add a unit test in `tests/unit/test_llm.py` that mocks `litellm` and verifies that models in `MODEL_OVERRIDES` (like `o1-mini`) correctly use their overridden context windows/output caps.
3. Remove any truly dead code in `llm.py` related to model detection that is now handled by `litellm` natively.

## Rationale

There is currently a mismatch between code and docs regarding the default model, and the `MODEL_OVERRIDES` logic is untested, which could lead to incorrect token budgeting for certain models.

