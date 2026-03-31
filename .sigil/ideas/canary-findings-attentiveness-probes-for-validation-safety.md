---
title: 'Canary Findings: Attentiveness Probes for Validation Safety'
summary: Implement 'Contextual Hallucination Triggering' (CHT) as a safety layer in
  `sigil.pipeline.validation`. The Validator ag
status: done
complexity: medium
disposition: issue
priority: 3
boldness: experimental
created: '2026-03-29T18:59:35Z'
---

# Canary Findings: Attentiveness Probes for Validation Safety

## Description

Implement 'Contextual Hallucination Triggering' (CHT) as a safety layer in `sigil.pipeline.validation`. The Validator agent periodically injects 'Canary Findings'—deliberate, slightly-hallucinated or subtly-wrong findings—into the stream of real findings. If the Triager/Challenger agents approve these canaries, it flags the run as 'low-reliability' and triggers a mandatory human-review disposition for all items in that run. This measures the 'attentiveness' of the LLM in the current run context. Add a `generate_canary` method to `Maintenance` and a matching detector in `Validation`.

## Rationale

LLMs can enter 'yes-man' loops where they approve everything to reach the end. CHT provides a real-time 'attention check' for the autonomous pipeline.

