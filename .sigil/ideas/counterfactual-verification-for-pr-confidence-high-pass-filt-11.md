---
title: Counterfactual Verification for PR Confidence High-Pass Filter
summary: Introduce a 'Confidence Scored Execution' (CSE) layer in sigil.pipeline.validation.
  For every approved item, the Triager
status: open
complexity: medium
disposition: pr
priority: 5
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Counterfactual Verification for PR Confidence High-Pass Filter

## Description

Introduce a 'Confidence Scored Execution' (CSE) layer in sigil.pipeline.validation. For every approved item, the Triager must assign a 'Confidence Score' (1-10). Items with score < 7 are automatically routed to a 'Challenger' agent even in 'single' validation mode. If the Challenger vetoes, the item is downgraded to an issue immediately. Implementation: 1. Update 'review_item' tool schema to require a 'confidence' int. 2. Modify validate_all to trigger a Challenger pass for low-confidence items. 3. Update the PR body to include the confidence score and the reasoning for it.

## Rationale

Reduces 'PR Spam' by adding a high-pass filter for speculative changes. It allows Sigil to be 'Bold' in analysis but 'Conservative' in execution. Reference: sigil.pipeline.validation.validate_all.

