---
title: 'Adversarial Validation: The Skeptical Challenger Persona'
summary: Introduce 'Adversarial Validation' in `sigil.pipeline.validation`. In parallel
  mode, give one 'Challenger' agent the exp
status: open
complexity: medium
disposition: pr
priority: 2
boldness: experimental
created: '2026-03-31T00:14:08Z'
---

# Adversarial Validation: The Skeptical Challenger Persona

## Description

Introduce 'Adversarial Validation' in `sigil.pipeline.validation`. In parallel mode, give one 'Challenger' agent the explicit persona of a 'Skeptical Senior Maintainer' whose goal is to find reasons to VETO the item (e.g., 'this is out of scope', 'this adds too much complexity', 'this is a hallucination').

Implementation:
1. Update `validate_all()` to inject a specific 'Adversarial' system prompt into one of the challenger agents.
2. The prompt should instruct the agent to be hyper-critical and look for 'PR Spam' or 'Low-Value Refactors'.
3. The Arbiter agent's prompt is updated to weigh the Skeptic's concerns against the Triager's optimism.
4. This creates a 'High-Pass Filter' that ensures only high-confidence, high-value PRs make it through.

## Rationale

The project's hard rule is 'Conservative by default'. Currently, validation can be too lenient. Adding a dedicated 'Skeptic' persona in parallel mode directly implements the 'one bad PR kills trust' philosophy.

