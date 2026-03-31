---
title: 'Autonomous TDD: Spec-Driven Test Redlining'
summary: Implement a 'Spec-Driven Test Redlining' workflow in sigil.pipeline.executor.
  Before the Engineer agent modifies any pro
status: open
complexity: medium
disposition: pr
priority: 8
created: '2026-03-29T17:13:30Z'
---

# Autonomous TDD: Spec-Driven Test Redlining

## Description

Implement a 'Spec-Driven Test Redlining' workflow in sigil.pipeline.executor. Before the Engineer agent modifies any production code, the QA agent (using the existing Agent framework) must use a new 'write_test_spec' tool to create a 'Redline' test file (e.g., tests/sigil_redline_*.py). This test must fail on the current codebase but pass once the implementation_spec is fulfilled. The Engineer agent then works to make this specific test pass. This ensures TDD-like rigor and prevents regression or 'hallucinated' success where the agent thinks it fixed something that wasn't actually broken. Implementation: 1. Add 'write_test_spec' tool to QA agent in executor.py. 2. Modify the execution loop to require a passing 'Redline' test before calling 'done'. 3. Ensure these temporary tests are cleaned up or integrated into the main suite based on config.

## Rationale

The current executor relies on post-hooks (lint/test) which are reactive. Proactive TDD (Redlining) ensures the agent actually understands the failure state before attempting a fix, significantly increasing PR reliability. Reference: sigil.pipeline.executor.execute.

