---
title: 'The Skeptical Challenger: Adversarial Incentives for Validation'
summary: Introduce 'Adversarial Validation' in `sigil.pipeline.validation`. In parallel
  mode, give one 'Challenger' agent the per
status: open
complexity: medium
disposition: issue
priority: 9
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# The Skeptical Challenger: Adversarial Incentives for Validation

## Description

Introduce 'Adversarial Validation' in `sigil.pipeline.validation`. In parallel mode, give one 'Challenger' agent the persona of a 'Skeptical Senior Reviewer' who is incentivized to find reasons to VETO. Implementation: 1. Add a `persona` argument to the `Agent` class. 2. In `validation.py`, when creating the second challenger, set `persona="skeptical_reviewer"`. 3. Update the system prompt for this agent to focus on: 'Is this change actually necessary?', 'Does this introduce a new dependency?', 'Is the implementation spec too vague?'. 4. This creates a 'Red Team' effect in validation, significantly raising the bar for PRs.

## Rationale

LLMs are naturally 'helpful' and prone to 'yes-manning'. By explicitly instructing one agent to be a 'hater', we force the Arbiter to resolve real conflicts, leading to much higher quality PRs that are less likely to be rejected by humans.

