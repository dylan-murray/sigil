---
title: 'Shadow Mode: Reality-Calibration for New Installs'
summary: Implement a 'Shadow Mode' for the validation agents. When enabled, Sigil
  runs the full pipeline but instead of opening P
status: open
complexity: small
disposition: pr
priority: 4
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Shadow Mode: Reality-Calibration for New Installs

## Description

Implement a 'Shadow Mode' for the validation agents. When enabled, Sigil runs the full pipeline but instead of opening PRs, it creates a 'Shadow Report' comparing its decisions against the actual recent commit history of the repository.

Implementation:
1. Add `shadow_mode: bool` to `Config`.
2. If true, during `analyze()`, Sigil looks at commits from the last 7 days.
3. It tries to 'predict' which files were changed and why.
4. It outputs a `shadow_report.md` in `.sigil/traces/` showing: 'I would have suggested X, and a human actually did Y.'
5. This serves as a calibration tool for users to tune `boldness` before letting Sigil go live.

## Rationale

Users are often afraid to run autonomous agents. Shadow Mode provides a 'safe' way to demonstrate value by showing how Sigil's proposals align with actual project evolution.

