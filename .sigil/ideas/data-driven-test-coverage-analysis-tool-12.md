---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a `sigil.pipeline.maintenance.check_test_coverage` tool that (if `pytest-cov`
  is available) reads coverage reports.
status: open
complexity: medium
disposition: pr
priority: 7
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a `sigil.pipeline.maintenance.check_test_coverage` tool that (if `pytest-cov` is available) reads coverage reports. Findings can then be automatically generated for 'low coverage' modules. This directly addresses the 'tests' focus area in `config.yml` with data-driven insights rather than just LLM intuition.

## Rationale

The 'tests' focus area is currently LLM-driven. Integrating actual coverage data makes the agent much more effective at improving the test suite.

