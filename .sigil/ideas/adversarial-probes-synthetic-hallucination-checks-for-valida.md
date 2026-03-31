---
title: 'Adversarial Probes: Synthetic Hallucination Checks for Validation Safety'
summary: Introduce 'Adversarial Prompt Injection Probes' (APIP) during validation.
  To ensure the Triager isn't just 'yes-manning'
status: open
complexity: medium
disposition: issue
priority: 3
boldness: experimental
created: '2026-03-31T00:14:08Z'
---

# Adversarial Probes: Synthetic Hallucination Checks for Validation Safety

## Description

Introduce 'Adversarial Prompt Injection Probes' (APIP) during validation. To ensure the Triager isn't just 'yes-manning' the Auditor's findings, Sigil will occasionally inject a 'Lure Finding'—a finding that looks plausible but contains a subtle, logically impossible statement or a reference to a non-existent file. Implementation: 1. In validation.py, if boldness is 'experimental', the system generates one 'synthetic hallucination'. 2. If the Triager approves the lure, the run's 'Confidence Metric' is downgraded and a warning is logged in the trace. 3. This forces the Validator to actually verify the 'Rationale' and 'File Exists' tags rather than skimming.

## Rationale

LLM triagers often suffer from 'confirmation bias'—if an auditor says there is a bug, the triager tends to agree. Probing the triager with intentional hallucinations is a standard safety technique for autonomous agents to maintain focus.

