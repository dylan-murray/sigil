---
title: 'Shadow Mode: Reality-Calibration for New Installs'
summary: "Implement a 'Shadow Mode' flag in `sigil.core.config.Config`. When enabled,\
  \ Sigil runs the entire pipeline\u2014including exe"
status: open
complexity: small
disposition: pr
priority: 6
boldness: balanced
created: '2026-03-31T00:41:14Z'
---

# Shadow Mode: Reality-Calibration for New Installs

## Description

Implement a 'Shadow Mode' flag in `sigil.core.config.Config`. When enabled, Sigil runs the entire pipeline—including execution and test passing—but instead of opening PRs or Issues, it writes a 'Shadow Report' to `.sigil/shadow-run.md` detailing exactly what it *would* have done, including the diffs it generated. This allows new users to 'calibrate' Sigil's boldness and focus settings safely on their codebase before giving it write access to GitHub. Implementation involves a simple check in `publish_results` to redirect output to a local file.

## Rationale

Trust is the primary barrier to adoption for autonomous agents. Shadow Mode provides a zero-risk way for users to audit Sigil's behavior on their specific private codebases.

