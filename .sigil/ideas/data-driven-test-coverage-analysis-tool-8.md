---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`.
  This tool will attempt to run `py
status: open
complexity: medium
disposition: issue
priority: 5
boldness: experimental
created: '2026-03-29T18:59:35Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`. This tool will attempt to run `pytest --cov` (if available) and return a summary of files with low coverage. The Auditor can then use this data to generate 'Maintenance' findings for missing tests. Implementation: 1. Add `check_test_coverage` to `MaintenanceAgent` tools. 2. The tool should look for `.coverage` or run a quick coverage check on a subset of files. 3. Update the Auditor's system prompt to encourage checking coverage when the 'tests' focus area is enabled. 4. Ensure the tool fails gracefully if `pytest-cov` is not installed.

## Rationale

Sigil has a 'tests' focus area, but it currently relies on the LLM 'guessing' what is untested by looking at file names. Real coverage data would allow Sigil to open high-value PRs that specifically target untested logic.

