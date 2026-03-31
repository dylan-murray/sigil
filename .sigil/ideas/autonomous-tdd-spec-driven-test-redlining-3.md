---
title: 'Autonomous TDD: Spec-Driven Test Redlining'
summary: Implement a 'Spec-Driven Test Redlining' workflow in `sigil.pipeline.executor`.
  Before the Engineer agent modifies any p
status: open
complexity: medium
disposition: pr
priority: 3
created: '2026-03-29T16:46:19Z'
---

# Autonomous TDD: Spec-Driven Test Redlining

## Description

Implement a 'Spec-Driven Test Redlining' workflow in `sigil.pipeline.executor`. Before the Engineer agent modifies any production code, the QA agent must first use a new `write_test_redline` tool to create a failing test case that reproduces the bug or defines the new feature's success criteria. The Engineer then implements the fix/feature until the redline test passes. This ensures TDD principles are followed autonomously. Implementation: 1. Add `write_test_redline` tool to the QA agent in `executor.py`. 2. Modify the execution loop to call QA for redlining before the Engineer starts. 3. The Engineer's 'done' condition now includes passing the redline test. 4. Update `ExecutionResult` to track redline status.

## Rationale

Sigil currently relies on post-hoc testing. Implementing autonomous TDD (redlining) significantly increases the reliability of PRs and ensures that every change is backed by a reproducing test case, which is a hallmark of high-quality engineering.

