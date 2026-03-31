---
title: 'Dark Code Detection: Coverage-Guided Maintenance Analysis'
summary: Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`.
  This tool will look for `.coverag
status: open
complexity: small
disposition: pr
priority: 5
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Dark Code Detection: Coverage-Guided Maintenance Analysis

## Description

Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`. This tool will look for `.coverage` files or attempt to run `pytest --cov` (if available) to identify 'Dark Code'—production logic that is not touched by any tests. Implementation: 1. Add `check_test_coverage` to `MaintenanceAgent` tools. 2. Tool runs `pytest --cov --cov-report=json` and parses the output. 3. Auditor uses this to prioritize findings in uncovered areas, as these are higher risk and need maintenance. 4. Findings in 'Dark Code' get a `priority` boost and a specific `category="coverage"`.

## Rationale

Sigil currently finds bugs via static analysis/LLM intuition. Adding dynamic coverage data allows it to target the most dangerous parts of a codebase—the parts that aren't tested. This makes Sigil a much more 'senior' auditor.

