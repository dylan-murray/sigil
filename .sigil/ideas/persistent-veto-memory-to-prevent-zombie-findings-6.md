---
title: Persistent Veto Memory to prevent 'Zombie Findings'
summary: Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding
  or idea is vetoed by a human (detected by a h
status: open
complexity: medium
disposition: pr
priority: 3
boldness: experimental
created: '2026-03-29T20:19:02Z'
---

# Persistent Veto Memory to prevent 'Zombie Findings'

## Description

Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding or idea is vetoed by a human (detected by a human closing a Sigil-opened PR or Issue without merging), Sigil should record the fingerprint of that item.

Implementation:
1. In `sigil.integrations.github.fetch_existing_issues`, also fetch recently closed issues/PRs with the 'sigil' label.
2. If an item was closed but NOT merged/completed, extract its fingerprint from the body.
3. Add a `veto_history` field to `WorkingMemory` in `sigil.state.memory`.
4. In `analyze()` and `ideate()`, provide this `veto_history` to the agents and instruct them NEVER to re-propose items that match these fingerprints.
5. This prevents 'Zombie Findings' where Sigil keeps proposing the same refactor that a human has already rejected.

## Rationale

Sigil currently lacks a 'long-term memory' for human rejections. Without this, it risks annoying maintainers by repeatedly opening the same rejected PRs in subsequent runs.

