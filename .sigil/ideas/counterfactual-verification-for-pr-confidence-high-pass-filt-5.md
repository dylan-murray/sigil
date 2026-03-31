---
title: Counterfactual Verification for PR Confidence High-Pass Filter
summary: Introduce 'Confidence Scored Execution' (CSE) in sigil.pipeline.validation.
  For every approved item, the Triager must no
status: open
complexity: medium
disposition: issue
priority: 3
created: '2026-03-29T17:47:08Z'
---

# Counterfactual Verification for PR Confidence High-Pass Filter

## Description

Introduce 'Confidence Scored Execution' (CSE) in sigil.pipeline.validation. For every approved item, the Triager must now assign a 'Confidence Score' (1-10) and a 'Verification Strategy' (e.g., 'check_types', 'run_specific_test').

Implementation:
1. Update `ReviewDecision` in `sigil.pipeline.validation` to include `confidence: int` and `verification_strategy: str`.
2. In `execute_parallel`, items with confidence < 7 are automatically downgraded to issues unless the user has `boldness: experimental`.
3. The `verification_strategy` is injected into the Engineer agent's prompt as a mandatory first step.
4. If the Engineer cannot verify the issue using the strategy (e.g., the type error doesn't show up), it must self-veto.

This adds a 'sanity check' layer that prevents low-confidence hallucinations from reaching the PR stage.

## Rationale

Architecture.md emphasizes 'Conservative by default'. CSE provides a quantitative way to enforce this, ensuring that only high-certainty items consume the execution budget and human reviewer time.

