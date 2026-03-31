---
title: 'Autonomous TDD: Spec-Driven Test Redlining'
summary: Implement 'Spec-Driven Test Redlining' in `sigil.pipeline.executor`. Before
  the Engineer agent modifies any production c
status: open
complexity: medium
disposition: issue
priority: 10
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Autonomous TDD: Spec-Driven Test Redlining

## Description

Implement 'Spec-Driven Test Redlining' in `sigil.pipeline.executor`. Before the Engineer agent modifies any production code, the QA agent must write a failing test that reproduces the bug or verifies the new feature based on the implementation spec. The Engineer then implements the fix/feature until the test passes. This ensures every Sigil PR is backed by a concrete, verified test case and prevents regression. Implementation: 1. Update `execute()` to first invoke the QA agent with the spec to create a new test file. 2. Run `post_hooks` to verify the test fails (Red phase). 3. Invoke Engineer agent to modify code. 4. Run `post_hooks` to verify the test passes (Green phase). 5. If Red phase fails (test passes immediately), the spec is likely already implemented or the test is invalid; abort and downgrade to issue.

## Rationale

Sigil's current execution flow is 'Engineer builds -> QA reviews/tests'. Reversing this to TDD (Test-Driven Development) significantly increases the reliability of autonomous PRs. It ensures that the LLM actually understands the problem before it starts changing code, which is the single biggest failure mode for autonomous agents.

