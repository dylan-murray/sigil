---
title: 'Temporal Revert: Automated ''Red'' Phase Verification for QA Agents'
summary: Introduce 'Sigil Time-Travel Verification' (TTV) as a sanity-check layer
  in the `sigil.pipeline.executor`. When an imple
status: open
complexity: large
disposition: issue
priority: 1
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Temporal Revert: Automated 'Red' Phase Verification for QA Agents

## Description

Introduce 'Sigil Time-Travel Verification' (TTV) as a sanity-check layer in the `sigil.pipeline.executor`. When an implementation is complete and passes hooks, Sigil performs a 'Temporal Revert': it checks out the original code, applies ONLY the newly written tests from the QA agent, and verifies they FAIL. Then it applies the code changes and verifies they PASS. This confirms the tests are actually checking the new functionality and aren't 'green' by accident or due to pre-existing conditions. Implementation involves: 1. In `executor.py`, after a successful run, stash the changes. 2. `git checkout` the original state. 3. Apply only files matching `test_*.py`. 4. Run `post_hooks` (expect failure). 5. Re-apply the full diff. 6. Run `post_hooks` (expect success). 7. If either expectation fails, the PR is blocked for 'Low Test Integrity'.

## Rationale

AI agents often hallucinate 'passing tests' that don't actually exercise the code they changed, or worse, they write tests that pass on the broken code. TTV is the only way to ensure the 'TDD' cycle was actually honest.

