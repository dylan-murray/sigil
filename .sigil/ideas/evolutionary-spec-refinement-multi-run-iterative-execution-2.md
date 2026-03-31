---
title: 'Evolutionary Spec Refinement: Multi-Run Iterative Execution'
summary: Introduce 'Evolutionary Spec Refinement' (ESR). When an execution fails after
  max retries, instead of just opening a 'Fa
status: open
complexity: medium
disposition: issue
priority: 5
created: '2026-03-29T17:47:08Z'
---

# Evolutionary Spec Refinement: Multi-Run Iterative Execution

## Description

Introduce 'Evolutionary Spec Refinement' (ESR). When an execution fails after max retries, instead of just opening a 'Failed Execution' issue, Sigil hands the failure log and the original spec back to the 'Architect' agent. The Architect analyzes the failure (e.g., 'The test kept failing because of a global state conflict') and produces a 'Refined Spec' for the NEXT run. This refined spec is stored in `.sigil/attempts.json` and automatically injected if the same finding is selected again. This allows Sigil to 'learn' why a specific fix is hard and try a different architectural approach in the next scheduled run. Update `state/attempts.py` to support `refined_spec` storage.

## Rationale

Currently, Sigil just gives up and opens an issue. ESR allows it to 'try a different way' across runs, effectively performing long-term problem solving.

