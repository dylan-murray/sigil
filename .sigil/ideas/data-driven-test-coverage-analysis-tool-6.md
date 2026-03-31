---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a `check_test_coverage` tool to the Auditor agent in sigil.pipeline.maintenance.
  This tool will attempt to run `pyte
status: open
complexity: medium
disposition: issue
priority: 8
created: '2026-03-29T17:47:08Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a `check_test_coverage` tool to the Auditor agent in sigil.pipeline.maintenance. This tool will attempt to run `pytest --cov` (if available) and return a summary of uncovered lines in the focus areas.

Implementation:
1. Add `check_test_coverage` to the `ToolFactory` in `maintenance.py`.
2. The tool runs `uv run pytest --cov --cov-report=json` and parses the output.
3. It filters for files in the `config.focus` areas.
4. The Auditor uses this data to generate 'Finding' objects with category 'tests' and high priority for uncovered critical paths.

This transforms 'test focus' from a generic LLM scan into a data-driven coverage improvement engine.

## Rationale

The 'tests' focus area is currently subjective. Using actual coverage data makes Sigil's test-improvement PRs objective and high-value. This bridges the gap between static analysis and dynamic execution.

