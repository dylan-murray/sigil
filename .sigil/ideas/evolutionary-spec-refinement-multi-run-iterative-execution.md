---
title: 'Evolutionary Spec Refinement: Multi-Run Iterative Execution'
summary: Introduce 'Evolutionary Spec Refinement' (ESR). When an execution fails after
  max retries, instead of just opening a fai
status: open
complexity: medium
disposition: pr
priority: 5
created: '2026-03-29T16:46:19Z'
---

# Evolutionary Spec Refinement: Multi-Run Iterative Execution

## Description

Introduce 'Evolutionary Spec Refinement' (ESR). When an execution fails after max retries, instead of just opening a failed issue, Sigil routes the failure back to the 'Architect' agent (using the Agent framework). The Architect analyzes the 'downgrade_context' (execution logs, test failures, linter errors) and the original 'implementation_spec'. It then produces a 'Refined Spec' (version 2) that explicitly addresses the failure reasons. This refined spec is saved in '.sigil/attempts/' and prioritized for the next run. This transforms 'failures' into 'learning steps', allowing the agent to overcome architectural hurdles over multiple scheduled runs rather than giving up.

## Rationale

Sigil's memory currently struggles with persistent state across runs (as noted in project context). ESR provides a structured way to handle multi-run problem solving, moving from a 1-shot execution model to an iterative, multi-day improvement cycle for complex features.

