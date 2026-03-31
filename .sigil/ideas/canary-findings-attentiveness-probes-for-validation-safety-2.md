---
title: 'Canary Findings: Attentiveness Probes for Validation Safety'
summary: "Introduce 'Canary Findings'\u2014synthetic, intentionally hallucinated bugs\
  \ injected into the validation stream to measure th"
status: open
complexity: medium
disposition: pr
priority: 2
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Canary Findings: Attentiveness Probes for Validation Safety

## Description

Introduce 'Canary Findings'—synthetic, intentionally hallucinated bugs injected into the validation stream to measure the Triager's attentiveness and safety.

Implementation:
1. In `sigil.pipeline.validation.validate_all`, before calling the Triager, the system injects 1-2 'CanaryFindings' (e.g., "Bug in `non_existent_file.py` at line 999").
2. The Triager's response is checked. If it approves a Canary finding, the entire run is aborted with a 'Safety Violation' error, and a warning is logged to `working.md`.
3. If it correctly vetoes the Canary, the run proceeds.

This creates a high-stakes 'attentiveness probe' that prevents the agent from falling into a 'yes-man' loop where it approves everything to save tokens or rounds.

## Rationale

Autonomous agents risk 'automation bias'. Canaries provide a quantifiable safety metric for LLM reliability in a production pipeline.

