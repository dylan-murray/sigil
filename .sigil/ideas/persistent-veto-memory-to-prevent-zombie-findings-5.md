---
title: Persistent Veto Memory to prevent 'Zombie Findings'
summary: Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding
  or idea is vetoed by a human (detected by a c
status: open
complexity: medium
disposition: pr
priority: 1
boldness: experimental
created: '2026-03-29T19:34:15Z'
---

# Persistent Veto Memory to prevent 'Zombie Findings'

## Description

Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding or idea is vetoed by a human (detected by a closed Sigil PR or issue without a merge, or a specific label), its fingerprint is added to a `veto_history` list in `working.md`. The Auditor and Ideator agents will receive this list in their system prompts and must skip any item that matches a vetoed fingerprint. This prevents Sigil from repeatedly proposing the same rejected changes in subsequent runs. Implementation: 1. Update `WorkingMemory` dataclass in `sigil.state.memory` to include `veto_history: list[str]`. 2. Add `fetch_vetoed_items` to `sigil.integrations.github` to scan for closed, unmerged Sigil PRs. 3. Update `update_working` to persist these fingerprints. 4. Inject `veto_history` into `analyze` and `ideate` prompts.

## Rationale

The working memory currently notes that 'Zombie Findings' (repeatedly proposing rejected items) is a known issue. This provides a concrete mechanism to learn from human rejection.

