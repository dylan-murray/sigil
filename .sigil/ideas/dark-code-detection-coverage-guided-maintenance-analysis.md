---
title: 'Dark Code Detection: Coverage-Guided Maintenance Analysis'
summary: Add a `check_test_coverage` tool to the `Auditor` agent in `sigil.pipeline.maintenance`.
  This tool will look for `.cover
status: open
complexity: small
disposition: pr
priority: 5
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Dark Code Detection: Coverage-Guided Maintenance Analysis

## Description

Add a `check_test_coverage` tool to the `Auditor` agent in `sigil.pipeline.maintenance`. This tool will look for `.coverage` files or run `pytest --cov` (if available) to identify 'Dark Code'—lines that are technically reachable but never executed in CI. This allows the Auditor to move beyond 'Unused Imports' and find 'Unused Logic,' which is a much higher-value target for deletion or testing. Implementation: 1. Update `maintenance.py` Auditor tools. 2. Handler runs `uv run pytest --cov` or parses existing XML/JSON coverage reports. 3. Findings are prioritized by 'Lines of Dark Code'.

## Rationale

Static analysis only catches the obvious. Dynamic coverage data allows Sigil to identify architectural 'dead weight' that humans are afraid to touch.

