---
title: 'Dark Code Detection: Coverage-Guided Maintenance Analysis'
summary: Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`.
  This tool will attempt to run the
status: open
complexity: small
disposition: pr
priority: 6
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Dark Code Detection: Coverage-Guided Maintenance Analysis

## Description

Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`. This tool will attempt to run the project's test suite with coverage enabled (e.g., `pytest --cov`) and parse the output.

Implementation:
1. Add `check_test_coverage` to `sigil.pipeline.maintenance.ToolFactory`.
2. The tool runs the `post_hooks` test command with coverage flags added.
3. It parses the coverage report (JSON or terminal output) to identify 'Dark Code' (files/functions with 0% coverage).
4. The Auditor uses this data to prioritize findings in untested areas, as these are higher risk for bugs.
5. This allows Sigil to be 'coverage-aware' when looking for improvements.

## Rationale

Currently, Sigil looks at code statically. Knowing which parts of the code are actually exercised by tests allows it to find 'Dark Code'—untested logic that is a prime candidate for either deletion (if dead) or hardening (if critical).

