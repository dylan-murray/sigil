---
title: 'Latent Style Inference: Learning Conventions from Git Archaeology'
summary: Implement 'Latent Style Inference' by performing a 'Git Archaeology' pass
  during discovery to extract the repo's actual
status: open
complexity: medium
disposition: pr
priority: 5
boldness: experimental
created: '2026-03-31T00:41:14Z'
---

# Latent Style Inference: Learning Conventions from Git Archaeology

## Description

Implement 'Latent Style Inference' by performing a 'Git Archaeology' pass during discovery to extract the repo's actual coding conventions from recent commits. Implementation: 1. Add `_infer_style(repo)` to `sigil.pipeline.discovery`. 2. Run `git log -p -n 10` to get the last 10 commits with diffs. 3. Pass these diffs to a specialized 'Archaeologist' agent to identify patterns: (e.g., 'prefers early returns', 'uses f-strings over format', 'strict type hinting', 'specific docstring format'). 4. Append these inferred rules to the `Instructions` object. 5. This allows Sigil to respect the 'vibe' of a repo even if it doesn't have an AGENTS.md or .cursorrules file.

## Rationale

Sigil currently relies on explicit config files (AGENTS.md). Many repos lack these. By 'reading the room' via git history, Sigil becomes much more 'human-like' and less likely to open PRs that violate unwritten team conventions, which is a major source of 'veto' actions.

