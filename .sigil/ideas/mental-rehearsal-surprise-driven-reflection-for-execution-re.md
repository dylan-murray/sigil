---
title: 'Mental Rehearsal: Surprise-Driven Reflection for Execution Retries'
summary: Add a `rehearsal` phase to the `Agent` framework in `sigil.core.agent`. Before
  the final `apply_edit` is committed in th
status: open
complexity: small
disposition: pr
priority: 8
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Mental Rehearsal: Surprise-Driven Reflection for Execution Retries

## Description

Add a `rehearsal` phase to the `Agent` framework in `sigil.core.agent`. Before the final `apply_edit` is committed in the executor, the agent is prompted to 'Rehearse the Diff'. It must generate a 1-sentence prediction of how the `post_hooks` (tests) will behave after the change. If the rehearsal prediction (e.g., 'Test X will pass') contradicts the actual outcome, the agent is forced into a 'Reflection' round where it analyzes the surprise before retrying. This mimics human debugging where 'surprises' are the primary signal for underlying misunderstandings. 1. Add `rehearse()` method to `Agent`. 2. Capture prediction. 3. Compare to `arun` results in `executor.py`.

## Rationale

Agents often 'blindly' retry without understanding why a test failed. Forcing a prediction makes the failure a 'violation of expectation,' which triggers better reasoning.

