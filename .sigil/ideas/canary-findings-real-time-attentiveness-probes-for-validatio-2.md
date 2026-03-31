---
title: 'Canary Findings: Real-time Attentiveness Probes for Validation Safety'
summary: Introduce 'Contextual Hallucination Probes' in the validation stage. Before
  reviewing real findings, the Triager is fed
status: open
complexity: medium
disposition: issue
priority: 12
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Canary Findings: Real-time Attentiveness Probes for Validation Safety

## Description

Introduce 'Contextual Hallucination Probes' in the validation stage. Before reviewing real findings, the Triager is fed a 'Canary' finding—a plausible but non-existent bug (e.g., 'Dead code in non-existent file X').

Implementation:
1. Add a `generate_canary(repo)` function that uses the LLM to invent a credible hallucination based on the repo's tech stack.
2. Inject this Canary into the list of findings passed to `validate_all`.
3. If the Triager approves the Canary as a legitimate bug/PR, the run is immediately flagged for quality degradation, and the Triager's other approvals are treated with high skepticism (or the run is aborted).
4. Results are tracked in `memory/working.md` to calibrate future confidence scores.

## Rationale

As LLMs get faster, 'yes-manning' (blindly approving findings) becomes a risk. Canaries provide a real-time metric for agent attentiveness and validation safety.

