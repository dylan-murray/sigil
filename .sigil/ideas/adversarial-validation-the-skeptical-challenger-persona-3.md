---
title: 'Adversarial Validation: The Skeptical Challenger Persona'
summary: Introduce 'Adversarial Validation' in sigil.pipeline.validation. In parallel
  mode, give one 'Challenger' the persona of
status: open
complexity: medium
disposition: pr
priority: 6
created: '2026-03-29T17:47:08Z'
---

# Adversarial Validation: The Skeptical Challenger Persona

## Description

Introduce 'Adversarial Validation' in sigil.pipeline.validation. In parallel mode, give one 'Challenger' the persona of a 'Skeptical Senior Architect' whose goal is to find reasons to VETO the item.

Implementation:
1. In `validation.py`, when `validation_mode == "parallel"`, set the `system_prompt` for the second Challenger to be adversarial.
2. The prompt instructs the agent: "Your job is to protect the codebase from unnecessary changes. Veto anything that is stylistic, low-impact, or potentially breaking."
3. The Arbiter then weighs the 'Proposer' (Triager) against the 'Skeptic' (Challenger).

This mimics a real-world code review process where one person is often more conservative, leading to higher quality PRs.

## Rationale

Parallel validation currently uses two identical personas. Adding a 'Skeptic' ensures that the 'Conservative by default' rule is actively enforced through dialectic tension rather than just prompt instructions.

