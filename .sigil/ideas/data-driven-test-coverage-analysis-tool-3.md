---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a `sigil.pipeline.maintenance.check_test_coverage` tool to the Auditor
  agent. If `pytest-cov` is detected in the env
status: open
complexity: medium
disposition: pr
priority: 7
created: '2026-03-29T15:44:20Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a `sigil.pipeline.maintenance.check_test_coverage` tool to the Auditor agent. If `pytest-cov` is detected in the environment, the tool runs a subset of tests related to the modified/analyzed files and returns the coverage percentage and missing lines. The Auditor can then use this data to generate 'Missing Coverage' findings with high priority. This transforms the Auditor from a static analyzer into a dynamic one that can identify untested logic paths. Implementation requires updating `sigil.pipeline.maintenance` to include the tool and logic to parse `.coverage` or XML reports.

## Rationale

Currently, Sigil relies on LLM 'intuition' to find missing tests. Providing actual coverage data allows it to make data-driven decisions about where to add tests, filling a major gap in the 'tests' focus area.

