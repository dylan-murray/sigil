---
title: 'Shadow Mode: Reality-Calibration for New Installs'
summary: "Implement a 'Shadow Mode' flag in `sigil.core.config.Config`. When enabled,\
  \ Sigil runs the entire pipeline\u2014including exe"
status: open
complexity: medium
disposition: pr
priority: 3
boldness: balanced
created: '2026-03-29T19:34:15Z'
---

# Shadow Mode: Reality-Calibration for New Installs

## Description

Implement a 'Shadow Mode' flag in `sigil.core.config.Config`. When enabled, Sigil runs the entire pipeline—including execution and testing—but instead of opening PRs, it simply logs the final diffs and test results to a local `shadow_run.json` file. Implementation: 1. Add `shadow_mode: bool` to `Config`. 2. In `publish_results`, if `shadow_mode` is True, skip GitHub calls and write to disk. 3. This allows users to 'test drive' Sigil on a new repo to see what it *would* do without any risk of noisy PRs. 4. It's also invaluable for debugging the pipeline itself.

## Rationale

Trust is the biggest barrier to adopting autonomous agents. Shadow mode allows maintainers to verify Sigil's quality and 'boldness' settings in a safe, read-only environment before going live.

