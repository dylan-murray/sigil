---
title: 'Canary Findings: Real-time Attentiveness Probes for Validation Safety'
summary: Introduce 'Contextual Hallucination Probes' in the `sigil.pipeline.validation`
  stage. Before the Triager reviews real fi
status: open
complexity: medium
disposition: issue
priority: 3
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Canary Findings: Real-time Attentiveness Probes for Validation Safety

## Description

Introduce 'Contextual Hallucination Probes' in the `sigil.pipeline.validation` stage. Before the Triager reviews real findings, the pipeline injects one 'Canary Finding'—a deliberately hallucinated bug in a non-existent file or a logically impossible error in a real file. If the Triager approves the Canary, the entire run is aborted/downgraded and a 'Safety Alert' is logged. This provides a real-time 'Attentiveness Score' for the model and prevents 'lazy' approvals during long validation passes. Implementation: 1. `validation.py` generates a canary finding. 2. Injects it into the `validate_all` list. 3. Checks the `review_item` output for the canary's index. 4. If action != 'veto', trigger safety failure.

## Rationale

Autonomous agents that approve their own hallucinations are the biggest risk to repo stability. Canaries turn the 'lazy model' problem into a hard stop.

