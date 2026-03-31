---
title: Counterfactual Verification for PR Confidence High-Pass Filter
summary: Introduce a 'Confidence Scored Execution' (CSE) layer in `sigil.pipeline.validation`.
  For every approved item, the Triag
status: open
complexity: medium
disposition: pr
priority: 8
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Counterfactual Verification for PR Confidence High-Pass Filter

## Description

Introduce a 'Confidence Scored Execution' (CSE) layer in `sigil.pipeline.validation`. For every approved item, the Triager must assign a confidence score (1-10). Items with score < 7 are automatically downgraded to 'issue' disposition regardless of the initial suggestion, unless a 'bold' or 'experimental' flag is set. Implementation: 1. Update `ReviewDecision` to include `confidence_score`. 2. Triager/Challenger agents must provide this score in the `review_item` tool. 3. In `validate_all`, apply the high-pass filter. 4. This acts as a 'Reality Check' that prevents Sigil from attempting complex refactors it isn't sure about.

## Rationale

Sigil sometimes 'hallucinates' its own capability to fix complex architectural issues. Forcing a confidence score and filtering on it reduces the number of failing, high-retry PRs that waste tokens and human attention.

