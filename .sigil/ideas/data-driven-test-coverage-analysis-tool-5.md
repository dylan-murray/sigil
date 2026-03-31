---
title: Data-Driven Test Coverage Analysis Tool
summary: Add a 'check_test_coverage' tool to the Auditor agent in sigil.pipeline.maintenance.
  This tool will attempt to run 'pyte
status: open
complexity: medium
disposition: pr
priority: 9
created: '2026-03-29T17:13:30Z'
---

# Data-Driven Test Coverage Analysis Tool

## Description

Add a 'check_test_coverage' tool to the Auditor agent in sigil.pipeline.maintenance. This tool will attempt to run 'pytest --cov' (or equivalent for the detected language) and return a summary of files with low coverage. The Auditor can then use this data to generate 'Finding' objects with category='tests' and high priority for critical paths. Implementation: 1. Add check_test_coverage to ToolFactory in maintenance.py. 2. Use arun() to execute coverage commands. 3. Parse the output (e.g., .coverage or terminal summary) and return it to the LLM. 4. Update the Auditor system prompt to encourage using coverage data to justify test-related findings.

## Rationale

Currently, Sigil 'guesses' where tests are missing by looking at file names. Real coverage data makes findings objective and high-value. Reference: sigil.pipeline.maintenance.analyze.

