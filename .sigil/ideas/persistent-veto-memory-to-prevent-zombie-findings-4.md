---
title: Persistent Veto Memory to prevent 'Zombie Findings'
summary: Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding
  or idea is vetoed by a human (detected by a h
status: open
complexity: medium
disposition: issue
priority: 14
created: '2026-03-29T17:47:08Z'
---

# Persistent Veto Memory to prevent 'Zombie Findings'

## Description

Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding or idea is vetoed by a human (detected by a human closing a Sigil PR with 'won't fix' or similar keywords), Sigil stores the fingerprint of that item in a permanent `vetoed_fingerprints` list in `working.md`. In all future runs, the Auditor and Ideator agents are explicitly told to skip these fingerprints. This prevents 'Zombie Findings'—issues that the maintainers have clearly stated they don't want to fix, but which Sigil's logic keeps finding every run. Update `integrations/github.py` to detect these closures.

## Rationale

Nothing is more annoying than an automated tool that keeps opening the same PR you already rejected. Persistent veto memory is essential for long-term project harmony.

