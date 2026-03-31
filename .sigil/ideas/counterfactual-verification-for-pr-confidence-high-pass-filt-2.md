---
title: Counterfactual Verification for PR Confidence High-Pass Filter
summary: Introduce a 'Confidence Scored Execution' (CSE) layer in `sigil.pipeline.validation`.
  For every approved item, the Triag
status: open
complexity: medium
disposition: pr
priority: 8
created: '2026-03-29T15:44:20Z'
---

# Counterfactual Verification for PR Confidence High-Pass Filter

## Description

Introduce a 'Confidence Scored Execution' (CSE) layer in `sigil.pipeline.validation`. For every approved item, the Triager must assign a 'Confidence Score' (1-10). Items with score < 7 are automatically downgraded to issues, regardless of their disposition. For items with score >= 7, a 'Counterfactual Verification' step is run: a 'Challenger' agent is given the implementation spec and asked to find 3 reasons why this change might break the build or violate project patterns. If the Challenger finds a 'Critical' risk, the item is downgraded. This acts as a high-pass filter for PR quality.

## Rationale

Sigil's reputation depends on PR quality. A 'guilty until proven innocent' approach to code generation ensures that only the most certain and well-vetted changes reach the PR stage.

