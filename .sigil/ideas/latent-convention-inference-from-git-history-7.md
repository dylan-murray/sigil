---
title: Latent Convention Inference from Git History
summary: Implement 'Latent Instruction Discovery' in `sigil.core.instructions`. Beyond
  just reading AGENTS.md, Sigil should scan
status: open
complexity: small
disposition: pr
priority: 4
boldness: balanced
created: '2026-03-29T20:19:02Z'
---

# Latent Convention Inference from Git History

## Description

Implement 'Latent Instruction Discovery' in `sigil.core.instructions`. Beyond just reading AGENTS.md, Sigil should scan the last 50 commit messages and PR descriptions for patterns of 'Revert' or 'Fixup' to identify 'Unwritten Rules' (e.g., 'always use double quotes in this repo' or 'never use library X'). These discovered constraints are injected into the system prompt as a 'Learned Conventions' block. This allows Sigil to adapt to a team's unspoken style without requiring manual AGENTS.md maintenance.

## Rationale

Agents often fail because they violate repo-specific 'tribal knowledge' not captured in static config. Modern LLMs are excellent at inferring latent patterns from history.

