---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`.
  This tool will attempt to run `py
status: open
complexity: medium
disposition: issue
priority: 10
created: '2026-03-29T18:16:01Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a `check_test_coverage` tool to the Auditor agent in `sigil.pipeline.maintenance`. This tool will attempt to run `pytest --cov` (or equivalent for the detected language) and parse the output to identify 'dark corners' of the codebase with zero or low coverage. The Auditor can then prioritize findings for missing tests in these specific areas. Implementation: 1. Add `check_test_coverage` to `Auditor` tools. 2. Tool runs a coverage command via `arun` and returns a summary of files with < 50% coverage. 3. Update Auditor system prompt to encourage checking coverage before reporting 'missing test' findings. 4. This transforms 'missing tests' from a guess into a data-driven finding.

## Rationale

Currently, Sigil's 'missing test' findings are based on heuristics. Using actual coverage data makes these findings much more accurate and valuable for maintainers.

