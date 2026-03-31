---
title: 'Ghost Notes: Non-Intrusive Architectural Debt Tracking via Git Metadata'
summary: Introduce 'Sigil Ghost Mode' using `git notes`. When Sigil is running in
  a shared repository, instead of only opening PR
status: open
complexity: large
disposition: issue
priority: 7
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Ghost Notes: Non-Intrusive Architectural Debt Tracking via Git Metadata

## Description

Introduce 'Sigil Ghost Mode' using `git notes`. When Sigil is running in a shared repository, instead of only opening PRs or issues, it can leave 'Ghost Comments'—architectural observations, debt markers, or 'refactor me' hints—attached to specific commits or lines via the `git notes` metadata layer. These observations don't pollute the source code but are visible to developers using `git log` or Sigil-aware IDE plugins. This allows Sigil to provide value as a 'Silent Architect' without the overhead of tracking thousands of GitHub issues for minor observations. Implementation: 1. New `publish_ghost_notes()` in `github.py`. 2. Uses `git notes add` to attach Finding content to objects. 3. Pushes notes to `refs/notes/sigil`.

## Rationale

Not every observation deserves an issue. Ghost notes provide a non-intrusive way for Sigil to build a 'Long-Term Memory' of technical debt directly in the git history.

