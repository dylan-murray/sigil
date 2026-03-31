---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`.
  This tool will attempt to run `py
status: open
complexity: medium
disposition: pr
priority: 4
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`. This tool will attempt to run `pytest --cov` (or equivalent for the detected language) and parse the output to identify files or functions with low coverage. The Auditor can then use this data to generate high-priority findings for missing tests. Implementation: 1. Add `check_test_coverage` to `AuditorAgent` tools. 2. Implement logic to detect the test runner and coverage tool. 3. Use `arun` to execute the coverage command. 4. Parse the output (e.g., from a `.coverage` file or stdout) and return a summary to the agent. 5. Update the Auditor's system prompt to encourage using coverage data when the 'tests' focus is active.

## Rationale

Sigil currently relies on LLM intuition to find missing tests. Providing actual coverage data makes the 'tests' focus area data-driven and much more accurate.

