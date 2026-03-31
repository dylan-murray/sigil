---
title: 'Autonomous TDD: Spec-Driven Test Redlining'
summary: Implement a 'Spec-Driven Test Redlining' workflow in `sigil.pipeline.executor`.
  Before the Engineer agent modifies any p
status: open
complexity: medium
disposition: pr
priority: 5
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Autonomous TDD: Spec-Driven Test Redlining

## Description

Implement a 'Spec-Driven Test Redlining' workflow in `sigil.pipeline.executor`. Before the Engineer agent modifies any production code, the QA agent (using the same `Agent` framework) must write a new test file that reproduces the bug or exercises the new feature (the 'Red' phase). The Engineer then implements the fix/feature until the test passes (the 'Green' phase). This ensures every Sigil PR is backed by a concrete, verifiable test case and prevents regressions. Implementation involves adding a `test_first` flag to the executor and a new `Tool` for the QA agent to create test files specifically in the `tests/` directory before the main execution loop starts.

## Rationale

Sigil's current execution flow is 'build then test'. Moving to a TDD-inspired 'test then build' approach significantly increases PR reliability and ensures that every automated change has a corresponding test, which is a high-bar requirement for autonomous agents.

