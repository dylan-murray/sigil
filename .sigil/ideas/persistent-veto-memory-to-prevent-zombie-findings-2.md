---
title: Persistent Veto Memory to prevent 'Zombie Findings'
summary: Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding
  or idea is vetoed by a human (by closing a Si
status: open
complexity: medium
disposition: pr
priority: 11
created: '2026-03-29T16:46:19Z'
---

# Persistent Veto Memory to prevent 'Zombie Findings'

## Description

Implement a 'Veto History' tracker in `sigil.state.memory`. When a finding or idea is vetoed by a human (by closing a Sigil PR/issue without merging) or by the Validator agent, its fingerprint is added to a persistent `veto_history` list in `working.md`. Implementation: 1. `GitHubClient` identifies closed-unmerged Sigil PRs. 2. `validate_all` checks the `veto_history` before presenting items to the Triager. 3. Items in the history are silently dropped. 4. This prevents 'Zombie Findings'—issues that Sigil finds every single run even though the maintainer has already signaled they don't want them fixed.

## Rationale

One of the most annoying behaviors of autonomous agents is re-proposing the same 'fix' that a maintainer has already rejected. Persistent veto memory respects human decisions across runs.

