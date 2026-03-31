---
title: 'Ghost Commits: Non-Intrusive Architectural Debt Tracking via Git Notes'
summary: "Introduce 'Ghost Commits'\u2014a mechanism where Sigil leaves 'Architectural\
  \ Debt' markers in git notes without touching the"
status: open
complexity: medium
disposition: issue
priority: 3
created: '2026-03-29T17:13:30Z'
---

# Ghost Commits: Non-Intrusive Architectural Debt Tracking via Git Notes

## Description

Introduce 'Ghost Commits'—a mechanism where Sigil leaves 'Architectural Debt' markers in git notes without touching the source code. When the Auditor agent finds a medium-risk issue that doesn't justify a PR or an Issue (to avoid spam), it uses a new `write_git_note` tool to attach a Sigil-finding to the relevant commit or file. These notes are then surfaced to humans via `git notes show` or used by Sigil in future runs to see if a 'smell' is getting worse over time. Implementation: 1. Add `write_git_note` tool to Auditor agent. 2. Use `git notes --ref sigil add -m <finding>` via arun. 3. Update discovery.py to read these notes as context.

## Rationale

Not every finding deserves a PR, but losing findings entirely is a waste of intelligence. Git notes provide a non-intrusive way to track 'code smells' that isn't as noisy as the GitHub Issue tracker.

